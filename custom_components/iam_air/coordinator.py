"""Data coordinator for IAM Air."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .cloud import IamAirAuthError, IamAirError, IamCloudClient
from .const import CONTROL_STATE_GRACE_SECONDS, DEFAULT_SCAN_INTERVAL_SECONDS, DOMAIN
from .models import DeviceSnapshot, IamAirDevice

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _PendingProperty:
    """A successfully written value waiting for cloud read-back."""

    value: object
    expires_at: float


def _reconcile_pending_properties(
    properties: dict[str, object],
    pending: dict[str, _PendingProperty],
    *,
    now: float,
) -> dict[str, object]:
    """Keep successful writes visible until the polling API catches up."""
    reconciled = dict(properties)
    for identifier, write in list(pending.items()):
        if reconciled.get(identifier) == write.value:
            pending.pop(identifier)
        elif now < write.expires_at:
            reconciled[identifier] = write.value
        else:
            pending.pop(identifier)
    return reconciled


class IamAirCoordinator(DataUpdateCoordinator[dict[str, DeviceSnapshot]]):
    """Poll all IAM air purifiers belonging to one account."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        config_entry: ConfigEntry,
        client: IamCloudClient,
        devices: list[IamAirDevice],
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS),
        )
        self.client = client
        self.devices = {device.iot_id: device for device in devices}
        self._pending_properties: dict[str, dict[str, _PendingProperty]] = {}

    async def _async_update_data(self) -> dict[str, DeviceSnapshot]:
        results = await asyncio.gather(
            *(
                self.client.async_get_properties(
                    iot_id,
                    iot_paas_type=device.iot_paas_type,
                )
                for iot_id, device in self.devices.items()
            ),
            return_exceptions=True,
        )
        snapshots: dict[str, DeviceSnapshot] = {}
        failures: list[Exception] = []
        for iot_id, result in zip(self.devices, results, strict=True):
            if isinstance(result, Exception):
                failures.append(result)
                previous = (self.data or {}).get(iot_id)
                snapshots[iot_id] = DeviceSnapshot(
                    properties=previous.properties if previous else {},
                    available=False,
                )
            else:
                pending = self._pending_properties.get(iot_id, {})
                properties = _reconcile_pending_properties(
                    result,
                    pending,
                    now=time.monotonic(),
                )
                if not pending:
                    self._pending_properties.pop(iot_id, None)
                snapshots[iot_id] = DeviceSnapshot(properties=properties)

        if failures and len(failures) == len(self.devices):
            error = failures[0]
            if isinstance(error, IamAirAuthError):
                raise ConfigEntryAuthFailed(
                    "IAM Air session is not authorized"
                ) from error
            raise UpdateFailed(f"Unable to update IAM Air devices: {error}") from error
        return snapshots

    async def async_set_properties(self, iot_id: str, items: dict[str, object]) -> None:
        """Write properties and request a fresh snapshot."""
        device = self.devices.get(iot_id)
        if device is None:
            raise UpdateFailed("Unable to control unknown IAM Air device")
        try:
            await self.client.async_set_properties(
                iot_id,
                items,
                iot_paas_type=device.iot_paas_type,
            )
        except IamAirError as err:
            raise UpdateFailed(f"Unable to control IAM Air device: {err}") from err

        expires_at = time.monotonic() + CONTROL_STATE_GRACE_SECONDS
        pending = self._pending_properties.setdefault(iot_id, {})
        pending.update(
            {
                identifier: _PendingProperty(value=value, expires_at=expires_at)
                for identifier, value in items.items()
            }
        )
        current = dict(self.data or {})
        previous = current.get(iot_id)
        optimistic = dict(previous.properties if previous else {})
        optimistic.update(items)
        current[iot_id] = DeviceSnapshot(
            properties=optimistic,
            available=previous.available if previous else True,
        )
        self.async_set_updated_data(current)
        await self.async_request_refresh()

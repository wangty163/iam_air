"""Data coordinator for IAM Air."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .cloud import IamAirAuthError, IamAirError, IamCloudClient
from .const import (
    CONTROL_STATE_GRACE_SECONDS,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    FOG_SCAN_INTERVAL_SECONDS,
    IOT_PAAS_TYPE_FOG,
)
from .models import DeviceSnapshot, IamAirDevice
from .mqtt import MqttPropertyPush

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _PendingProperty:
    """A successfully written value waiting for cloud read-back."""

    value: object
    expires_at: float


@dataclass(frozen=True, slots=True)
class _PushedProperty:
    """A timestamped property received from the App-compatible channel."""

    value: object
    timestamp: int


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
        scan_interval = (
            FOG_SCAN_INTERVAL_SECONDS
            if any(
                device.iot_paas_type == IOT_PAAS_TYPE_FOG for device in devices
            )
            else DEFAULT_SCAN_INTERVAL_SECONDS
        )
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.devices = {device.iot_id: device for device in devices}
        self._pending_properties: dict[str, dict[str, _PendingProperty]] = {}
        self._pushed_properties: dict[str, dict[str, _PushedProperty]] = {}
        self._push_connected = False

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
                device = self.devices[iot_id]
                if device.iot_paas_type == IOT_PAAS_TYPE_FOG:
                    self._pushed_properties.pop(iot_id, None)
                elif self._push_connected:
                    properties.update(
                        {
                            identifier: pushed.value
                            for identifier, pushed in self._pushed_properties.get(
                                iot_id, {}
                            ).items()
                        }
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

    async def async_set_properties(
        self,
        iot_id: str,
        items: dict[str, object],
        *,
        optimistic_items: dict[str, object] | None = None,
    ) -> None:
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

        visible_items = optimistic_items or items
        pushed = self._pushed_properties.get(iot_id, {})
        for identifier in visible_items:
            pushed.pop(identifier, None)
        if not pushed:
            self._pushed_properties.pop(iot_id, None)
        expires_at = time.monotonic() + CONTROL_STATE_GRACE_SECONDS
        pending = self._pending_properties.setdefault(iot_id, {})
        pending.update(
            {
                identifier: _PendingProperty(value=value, expires_at=expires_at)
                for identifier, value in visible_items.items()
            }
        )
        current = dict(self.data or {})
        previous = current.get(iot_id)
        optimistic = dict(previous.properties if previous else {})
        optimistic.update(visible_items)
        current[iot_id] = DeviceSnapshot(
            properties=optimistic,
            available=previous.available if previous else True,
        )
        self.async_set_updated_data(current)
        await self.async_request_refresh()

    @callback
    def async_apply_property_push(self, push: MqttPropertyPush) -> None:
        """Merge a newer MQTT property event into the active HA snapshot."""
        if push.iot_id not in self.devices:
            return
        pushed = self._pushed_properties.setdefault(push.iot_id, {})
        accepted: dict[str, object] = {}
        for identifier, item in push.items.items():
            previous = pushed.get(identifier)
            if previous is not None and item.timestamp < previous.timestamp:
                continue
            pushed[identifier] = _PushedProperty(
                value=item.value,
                timestamp=item.timestamp,
            )
            accepted[identifier] = item.value
        if not accepted:
            return

        self._push_connected = True
        pending = self._pending_properties.get(push.iot_id, {})
        for identifier in accepted:
            pending.pop(identifier, None)
        if not pending:
            self._pending_properties.pop(push.iot_id, None)

        current = dict(self.data or {})
        previous = current.get(push.iot_id)
        properties = dict(previous.properties if previous else {})
        properties.update(accepted)
        current[push.iot_id] = DeviceSnapshot(
            properties=properties,
            available=True,
        )
        self.async_set_updated_data(current)

    @callback
    def async_set_push_connected(self, connected: bool) -> None:
        """Track whether push values can safely override stale REST snapshots."""
        self._push_connected = connected
        if not connected:
            self._pushed_properties.clear()

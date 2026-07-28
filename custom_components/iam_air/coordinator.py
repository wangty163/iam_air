"""Data coordinator for IAM Air."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .cloud import IamAirAuthError, IamAirError, IamCloudClient
from .const import DEFAULT_SCAN_INTERVAL_SECONDS, DOMAIN
from .models import DeviceSnapshot, IamAirDevice

_LOGGER = logging.getLogger(__name__)


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

    async def _async_update_data(self) -> dict[str, DeviceSnapshot]:
        results = await asyncio.gather(
            *(self.client.async_get_properties(iot_id) for iot_id in self.devices),
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
                snapshots[iot_id] = DeviceSnapshot(properties=result)

        if failures and len(failures) == len(self.devices):
            error = failures[0]
            if isinstance(error, IamAirAuthError):
                raise ConfigEntryAuthFailed(
                    "IAM Air session is not authorized"
                ) from error
            raise UpdateFailed("Unable to update IAM Air devices") from error
        return snapshots

    async def async_set_properties(self, iot_id: str, items: dict[str, object]) -> None:
        """Write properties and request a fresh snapshot."""
        try:
            await self.client.async_set_properties(iot_id, items)
        except IamAirError as err:
            raise UpdateFailed("Unable to control IAM Air device") from err
        await self.async_request_refresh()

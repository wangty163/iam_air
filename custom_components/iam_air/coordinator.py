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

from .cloud import (
    IamAirAuthError,
    IamAirConnectionError,
    IamAirError,
    IamCloudClient,
)
from .const import (
    CLOUD_CONNECTION_GRACE_SECONDS,
    CONTROL_STATE_GRACE_SECONDS,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DEVICE_STATUS_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    FOG_SCAN_INTERVAL_SECONDS,
    IOT_PAAS_TYPE_FOG,
)
from .models import DeviceSnapshot, IamAirDevice
from .mqtt import MqttDeviceStatus, MqttPropertyPush

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
        self._device_online = {
            device.iot_id: device.online
            for device in devices
            if device.online is not None
        }
        self._next_device_status_refresh = 0.0
        self._pending_properties: dict[str, dict[str, _PendingProperty]] = {}
        self._pushed_properties: dict[str, dict[str, _PushedProperty]] = {}
        self._property_connection_failures: dict[str, float] = {}
        self._push_connected = False

    def _snapshot_during_connection_grace(
        self,
        iot_id: str,
        *,
        online: bool | None,
        error: IamAirConnectionError,
    ) -> DeviceSnapshot | None:
        """Retain the last good snapshot during a short cloud interruption."""
        previous = (self.data or {}).get(iot_id)
        if previous is None:
            return None

        now = time.monotonic()
        started_at = self._property_connection_failures.get(iot_id)
        if started_at is None:
            started_at = now
            self._property_connection_failures[iot_id] = started_at
            _LOGGER.warning(
                "IAM Air cloud property refresh failed; retaining the last "
                "successful snapshot for up to %d seconds: %s",
                CLOUD_CONNECTION_GRACE_SECONDS,
                error,
            )
        if now - started_at >= CLOUD_CONNECTION_GRACE_SECONDS:
            return None

        return DeviceSnapshot(
            properties=previous.properties,
            available=previous.available if online is None else online,
            online=online,
        )

    def _clear_property_connection_failure(self, iot_id: str) -> None:
        """Log recovery once after a tolerated cloud interruption."""
        started_at = self._property_connection_failures.pop(iot_id, None)
        if started_at is None:
            return
        _LOGGER.info(
            "IAM Air cloud property refresh recovered after %.1f seconds",
            max(0.0, time.monotonic() - started_at),
        )

    async def _async_update_data(self) -> dict[str, DeviceSnapshot]:
        now = time.monotonic()
        refresh_device_status = now >= self._next_device_status_refresh
        requests = [
            self.client.async_get_properties(
                iot_id,
                iot_paas_type=device.iot_paas_type,
            )
            for iot_id, device in self.devices.items()
        ]
        if refresh_device_status:
            requests.append(
                self.client.async_get_device_online_states(
                    {
                        iot_id: device.iot_paas_type
                        for iot_id, device in self.devices.items()
                    }
                )
            )
        results = list(
            await asyncio.gather(
                *requests,
                return_exceptions=True,
            )
        )
        if refresh_device_status:
            self._next_device_status_refresh = (
                time.monotonic() + DEVICE_STATUS_SCAN_INTERVAL_SECONDS
            )
            status_result = results.pop()
            if isinstance(status_result, Exception):
                _LOGGER.debug(
                    "Unable to refresh IAM Air device online states: %s",
                    status_result,
                )
            else:
                self._apply_device_online_states(status_result)

        snapshots: dict[str, DeviceSnapshot] = {}
        failures: list[Exception] = []
        for iot_id, result in zip(self.devices, results, strict=True):
            device_online = self._device_online.get(iot_id)
            if isinstance(result, Exception):
                if (
                    isinstance(result, IamAirConnectionError)
                    and device_online is not False
                ):
                    retained = self._snapshot_during_connection_grace(
                        iot_id,
                        online=device_online,
                        error=result,
                    )
                    if retained is not None:
                        snapshots[iot_id] = retained
                        continue
                else:
                    self._property_connection_failures.pop(iot_id, None)
                if isinstance(result, IamAirAuthError) or device_online is not False:
                    failures.append(result)
                previous = (self.data or {}).get(iot_id)
                snapshots[iot_id] = DeviceSnapshot(
                    properties=previous.properties if previous else {},
                    available=False,
                    online=device_online,
                )
            else:
                self._clear_property_connection_failure(iot_id)
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
                snapshots[iot_id] = DeviceSnapshot(
                    properties=properties,
                    available=device_online is not False,
                    online=device_online,
                )

        if failures and len(failures) == len(self.devices):
            error = failures[0]
            if isinstance(error, IamAirAuthError):
                raise ConfigEntryAuthFailed(
                    "IAM Air session is not authorized"
                ) from error
            raise UpdateFailed(f"Unable to update IAM Air devices: {error}") from error
        return snapshots

    def _apply_device_online_states(self, states: dict[str, bool]) -> None:
        """Apply authoritative App-route states and log device transitions."""
        for iot_id, online in states.items():
            device = self.devices.get(iot_id)
            if device is None:
                continue
            previous = self._device_online.get(iot_id)
            self._device_online[iot_id] = online
            if not online:
                self._property_connection_failures.pop(iot_id, None)
            if previous is not None and previous != online:
                _LOGGER.info(
                    "IAM Air device %s is now %s",
                    device.name,
                    "online" if online else "offline",
                )

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
            online=(
                previous.online if previous else self._device_online.get(iot_id)
            ),
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

        device = self.devices[push.iot_id]
        if device.iot_paas_type != IOT_PAAS_TYPE_FOG:
            self._apply_device_online_states({push.iot_id: True})
        device_online = self._device_online.get(push.iot_id)
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
            available=device_online is not False,
            online=device_online,
        )
        self.async_set_updated_data(current)

    @callback
    def async_apply_device_status(self, status: MqttDeviceStatus) -> None:
        """Apply an explicit FOG device connectivity event."""
        if status.iot_id not in self.devices:
            return
        self._apply_device_online_states({status.iot_id: status.online})
        current = dict(self.data or {})
        previous = current.get(status.iot_id)
        current[status.iot_id] = DeviceSnapshot(
            properties=previous.properties if previous else {},
            available=status.online,
            online=status.online,
        )
        self.async_set_updated_data(current)

    @callback
    def async_set_push_connected(self, connected: bool) -> None:
        """Track whether push values can safely override stale REST snapshots."""
        self._push_connected = connected
        if not connected:
            self._pushed_properties.clear()

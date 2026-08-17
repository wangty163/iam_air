"""Connectivity sensor for IAM air purifiers."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IamAirConfigEntry
from .entity import IamAirEntity, add_iam_entities
from .models import IamAirDevice


async def async_setup_entry(
    _hass: Any,
    entry: IamAirConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one connectivity sensor per purifier."""
    coordinator = entry.runtime_data.coordinator
    entities: list[IamAirEntity] = [
        IamAirConnectivityBinarySensor(coordinator, device)
        for device in coordinator.devices.values()
    ]
    add_iam_entities(entry, async_add_entities, entities)


class IamAirConnectivityBinarySensor(IamAirEntity, BinarySensorEntity):
    """Expose device availability without becoming unavailable itself."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "connectivity"

    def __init__(self, coordinator: Any, device: IamAirDevice) -> None:
        super().__init__(
            coordinator,
            device,
            unique_suffix="connectivity",
        )

    @property
    def available(self) -> bool:
        """Remain available while the coordinator can determine connectivity."""
        snapshot = (self.coordinator.data or {}).get(self.device.iot_id)
        return (
            self.coordinator.last_update_success
            and snapshot is not None
            and snapshot.online is not None
        )

    @property
    def is_on(self) -> bool | None:
        """Return whether the purifier is online."""
        snapshot = (self.coordinator.data or {}).get(self.device.iot_id)
        if snapshot is None:
            return None
        return snapshot.online

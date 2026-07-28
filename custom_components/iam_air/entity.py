"""Shared IAM Air entity helpers."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import IamAirCoordinator
from .models import IamAirDevice


def add_iam_entities(
    entry: Any,
    async_add_entities: AddEntitiesCallback,
    entities: list[IamAirEntity],
) -> None:
    """Register the active unique IDs before adding entities to HA."""
    entry.runtime_data.active_unique_ids.update(
        entity.unique_id for entity in entities if entity.unique_id is not None
    )
    async_add_entities(entities)


class IamAirEntity(CoordinatorEntity[IamAirCoordinator]):
    """Base entity bound to one discovered IAM air purifier."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: IamAirCoordinator,
        device: IamAirDevice,
        *,
        unique_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self.device = device
        self._attr_unique_id = f"{device.iot_id}_{unique_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.iot_id)},
            name=device.name,
            manufacturer="IAM",
            model=device.model,
        )

    @property
    def available(self) -> bool:
        """Return whether the coordinator has a live snapshot."""
        snapshot = (self.coordinator.data or {}).get(self.device.iot_id)
        return super().available and snapshot is not None and snapshot.available

    def property_value(self, identifier: str) -> Any:
        """Return one property from the latest snapshot."""
        snapshot = (self.coordinator.data or {}).get(self.device.iot_id)
        if snapshot is None:
            return None
        return snapshot.properties.get(identifier)

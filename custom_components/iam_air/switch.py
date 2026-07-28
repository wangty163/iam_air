"""Switch platform for IAM air purifiers."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IamAirConfigEntry
from .entity import IamAirEntity
from .models import IamAirDevice, TslProperty, value_as_bool

SWITCH_ALIASES = (
    ("childLockOnOff", "childLock", "ChildLock"),
    ("uvSterilization", "UVSwitch", "uvSwitch"),
    ("IonsSwitch", "ionsSwitch", "negativeIon"),
    ("disinfection", "Disinfection"),
    ("TrustSwitch", "trustSwitch"),
)


async def async_setup_entry(
    _hass: Any,
    entry: IamAirConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up writable purifier switches."""
    coordinator = entry.runtime_data.coordinator
    entities: list[IamAirSwitch] = []
    for device in coordinator.devices.values():
        seen: set[str] = set()
        for aliases in SWITCH_ALIASES:
            prop = device.find_property(*aliases)
            if (
                prop is None
                or not prop.readable
                or not prop.writable
                or prop.identifier in seen
            ):
                continue
            seen.add(prop.identifier)
            entities.append(IamAirSwitch(coordinator, device, prop))
    async_add_entities(entities)


class IamAirSwitch(IamAirEntity, SwitchEntity):
    """A writable boolean TSL property."""

    def __init__(
        self,
        coordinator: Any,
        device: IamAirDevice,
        prop: TslProperty,
    ) -> None:
        super().__init__(
            coordinator,
            device,
            unique_suffix=prop.identifier.lower(),
        )
        self._property = prop
        self._attr_name = prop.name

    @property
    def is_on(self) -> bool:
        """Return the current switch state."""
        return value_as_bool(self.value(self._property.identifier))

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Enable the property."""
        await self.coordinator.async_set_properties(
            self.device.iot_id,
            {self._property.identifier: self._property.coerce_value(1)},
        )

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Disable the property."""
        await self.coordinator.async_set_properties(
            self.device.iot_id,
            {self._property.identifier: self._property.coerce_value(0)},
        )

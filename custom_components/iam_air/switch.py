"""Switch platform for IAM air purifiers."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IamAirConfigEntry
from .const import POWER_PROPERTY_ALIASES
from .entity import IamAirEntity, add_iam_entities
from .models import IamAirDevice, TslProperty, value_as_bool

SWITCH_ALIASES = (
    POWER_PROPERTY_ALIASES,
    ("ChildLockSwitch", "childLockOnOff", "childLock", "ChildLock"),
    ("DisinfectSwitch", "disinfectSwitch", "disinfection", "Disinfection"),
    ("IonsSwitch", "ionsSwitch", "negativeIon"),
    ("ScreenSwitch", "screenSwitch"),
    ("Trusteeship", "TrustSwitch", "trustSwitch"),
    ("T_DisinfectSwitch",),
    ("T_IonsSwitch",),
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
    add_iam_entities(entry, async_add_entities, entities)


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
    def is_on(self) -> bool | None:
        """Return the current switch state."""
        value = self.property_value(self._property.identifier)
        if value is None:
            return None
        return value_as_bool(value)

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

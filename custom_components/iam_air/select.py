"""Select platform for IAM air-purifier enum controls."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IamAirConfigEntry
from .const import MODE_PROPERTY_ALIASES, SPEED_PROPERTY_ALIASES
from .entity import IamAirEntity, add_iam_entities, app_property_name
from .models import IamAirDevice, TslProperty

SELECT_ALIASES = (
    SPEED_PROPERTY_ALIASES,
    MODE_PROPERTY_ALIASES,
    ("T_ON_TVOCLevel",),
    ("T_OFF_TVOCLevel",),
)

APP_SELECT_OPTIONS = {
    "t_off_tvoclevel": {"0", "1", "2", "3"},
    "t_on_tvoclevel": {"0", "2", "3", "4"},
}


async def async_setup_entry(
    _hass: Any,
    entry: IamAirConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the App's named enum controls."""
    coordinator = entry.runtime_data.coordinator
    entities: list[IamAirSelect] = []
    for device in coordinator.devices.values():
        seen: set[str] = set()
        for aliases in SELECT_ALIASES:
            prop = device.find_property(*aliases)
            if (
                prop is None
                or not prop.readable
                or not prop.writable
                or not prop.enum_options
                or prop.identifier in seen
            ):
                continue
            seen.add(prop.identifier)
            entities.append(IamAirSelect(coordinator, device, prop))
    add_iam_entities(entry, async_add_entities, entities)


class IamAirSelect(IamAirEntity, SelectEntity):
    """A writable enum property with the labels used by the IAM App."""

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
        self._attr_name = app_property_name(device, prop)
        allowed_values = APP_SELECT_OPTIONS.get(prop.identifier.casefold())
        self._attr_options = [
            label
            for raw_value, label in prop.enum_options.items()
            if allowed_values is None or raw_value in allowed_values
        ]

    @property
    def current_option(self) -> str | None:
        """Return the selected App label."""
        return self._property.option_for_value(
            self.property_value(self._property.identifier)
        )

    async def async_select_option(self, option: str) -> None:
        """Select an enum option."""
        if self._property.identifier.casefold() in {
            "windspeed",
            "workmode",
            "fanspeed",
            "mode",
        }:
            self.ensure_app_control_allowed(require_power=True)
        value = self._property.value_for_option(option)
        if value is None:
            raise ValueError(f"Unsupported option: {option}")
        await self.coordinator.async_set_properties(
            self.device.iot_id,
            {self._property.identifier: self._property.coerce_value(value)},
        )

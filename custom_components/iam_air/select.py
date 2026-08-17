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

M8_PRO_MODEL = "KJ800F-M8 Pro"
M8_PRO_WIND_SPEED_OPTIONS = {
    "0": "自动",
    "1": "1档",
    "2": "2档",
    "3": "3档",
    "4": "4档",
    "5": "5档",
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
        self._uses_numbered_wind_speed_options = (
            device.model.casefold() == M8_PRO_MODEL.casefold()
            and prop.identifier.casefold() == "windspeed"
            and set(prop.enum_options) == set(M8_PRO_WIND_SPEED_OPTIONS)
        )
        option_labels = (
            M8_PRO_WIND_SPEED_OPTIONS
            if self._uses_numbered_wind_speed_options
            else prop.enum_options
        )
        allowed_values = APP_SELECT_OPTIONS.get(prop.identifier.casefold())
        self._attr_options = [
            label
            for raw_value, label in option_labels.items()
            if allowed_values is None or raw_value in allowed_values
        ]

    @property
    def current_option(self) -> str | None:
        """Return the selected App label."""
        value = self.property_value(self._property.identifier)
        if self._uses_numbered_wind_speed_options:
            return M8_PRO_WIND_SPEED_OPTIONS.get(str(value))
        return self._property.option_for_value(value)

    async def async_select_option(self, option: str) -> None:
        """Select an enum option."""
        if self._property.identifier.casefold() in {
            "windspeed",
            "workmode",
            "fanspeed",
            "mode",
        }:
            self.ensure_app_control_allowed(require_power=True)
        if self._uses_numbered_wind_speed_options:
            value = next(
                (
                    raw
                    for raw, label in M8_PRO_WIND_SPEED_OPTIONS.items()
                    if label == option
                ),
                None,
            )
        else:
            value = self._property.value_for_option(option)
        if value is None:
            raise ValueError(f"Unsupported option: {option}")
        await self.coordinator.async_set_properties(
            self.device.iot_id,
            {self._property.identifier: self._property.coerce_value(value)},
        )

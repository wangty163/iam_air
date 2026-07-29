"""Number platform for IAM air-purifier timer and trusteeship controls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfTime
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IamAirConfigEntry
from .entity import IamAirEntity, add_iam_entities, app_property_name
from .models import IamAirDevice, TslProperty, value_as_bool
from .sensor import normalize_unit


@dataclass(frozen=True, slots=True)
class IamNumberSpec:
    """One App number control."""

    aliases: tuple[str, ...]
    default_unit: str | None = None


NUMBER_SPECS = (
    IamNumberSpec(("TimingOn",), UnitOfTime.HOURS),
    IamNumberSpec(("TimingOff",), UnitOfTime.HOURS),
    IamNumberSpec(("T_ON_HCHO",)),
    IamNumberSpec(("T_OFF_HCHO",)),
    IamNumberSpec(("T_ON_PM25",)),
    IamNumberSpec(("T_OFF_PM25",)),
)

APP_NUMBER_RANGES = {
    "t_off_hcho": (0.0, 0.1, 0.01),
    "t_off_pm25": (0.0, 110.0, 5.0),
    "t_on_hcho": (0.0, 0.1, 0.01),
    "t_on_pm25": (0.0, 110.0, 5.0),
}


async def async_setup_entry(
    _hass: Any,
    entry: IamAirConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up numeric controls exposed by the App."""
    coordinator = entry.runtime_data.coordinator
    entities: list[IamAirNumber] = []
    for device in coordinator.devices.values():
        seen: set[str] = set()
        for spec in NUMBER_SPECS:
            prop = device.find_property(*spec.aliases)
            if (
                prop is None
                or not prop.readable
                or not prop.writable
                or prop.numeric_range is None
                or prop.identifier in seen
            ):
                continue
            seen.add(prop.identifier)
            entities.append(
                IamAirNumber(
                    coordinator,
                    device,
                    prop=prop,
                    default_unit=spec.default_unit,
                )
            )
    add_iam_entities(entry, async_add_entities, entities)


class IamAirNumber(IamAirEntity, NumberEntity):
    """A writable numeric TSL property."""

    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator: Any,
        device: IamAirDevice,
        *,
        prop: TslProperty,
        default_unit: str | None,
    ) -> None:
        super().__init__(
            coordinator,
            device,
            unique_suffix=prop.identifier.lower(),
        )
        self._property = prop
        self._attr_name = app_property_name(device, prop)
        minimum, maximum, step = APP_NUMBER_RANGES.get(
            prop.identifier.casefold(),
            prop.numeric_range or (0.0, 100.0, 1.0),
        )
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = normalize_unit(
            prop.unit or default_unit
        )

    @property
    def native_value(self) -> float | None:
        """Return the current numeric value."""
        value = self.property_value(self._property.identifier)
        if value is None:
            return None
        try:
            return float(value)
        except TypeError, ValueError:
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Set a numeric App control."""
        identifier = self._property.identifier.casefold()
        power_on = value_as_bool(self.property_value("PowerSwitch"))
        if identifier == "timingoff":
            self.ensure_app_control_allowed(require_power=True)
        elif identifier == "timingon":
            self.ensure_app_control_allowed(require_power=False)
            if power_on:
                raise HomeAssistantError("设备已开机, 请使用定时关机")
        await self.coordinator.async_set_properties(
            self.device.iot_id,
            {self._property.identifier: self._property.coerce_value(value)},
        )

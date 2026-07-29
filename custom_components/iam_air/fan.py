"""Fan platform for IAM air purifiers."""

from __future__ import annotations

import math
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IamAirConfigEntry
from .const import (
    MODE_PROPERTY_ALIASES,
    POWER_PROPERTY_ALIASES,
    SPEED_PROPERTY_ALIASES,
)
from .entity import IamAirEntity, add_iam_entities
from .models import (
    IamAirDevice,
    percentage_for_property,
    value_as_bool,
    value_for_percentage,
)


async def async_setup_entry(
    _hass: Any,
    entry: IamAirConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up purifier fan entities."""
    coordinator = entry.runtime_data.coordinator
    add_iam_entities(
        entry,
        async_add_entities,
        [
            IamAirFan(coordinator, device)
            for device in coordinator.devices.values()
        ],
    )


class IamAirFan(IamAirEntity, FanEntity):
    """Primary fan entity for an IAM air purifier."""

    _attr_name = None

    def __init__(self, coordinator: Any, device: IamAirDevice) -> None:
        super().__init__(coordinator, device, unique_suffix="fan")
        self._power = device.find_property(*POWER_PROPERTY_ALIASES)
        self._speed = device.find_property(*SPEED_PROPERTY_ALIASES)
        self._mode = device.find_property(*MODE_PROPERTY_ALIASES)

        features = FanEntityFeature(0)
        if self._power and self._power.writable:
            features |= FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
        if self._speed and self._speed.writable:
            features |= FanEntityFeature.SET_SPEED
        if self._mode and self._mode.writable and self._mode.enum_options:
            features |= FanEntityFeature.PRESET_MODE
        self._attr_supported_features = features

    @property
    def is_on(self) -> bool | None:
        """Return the purifier power state."""
        if self._power is None:
            return None
        return value_as_bool(self.property_value(self._power.identifier))

    @property
    def percentage(self) -> int | None:
        """Return current fan speed as a Home Assistant percentage."""
        if self._speed is None:
            return None
        raw = self.property_value(self._speed.identifier)
        if raw is None:
            return None
        if app_values := self._app_manual_speed_values:
            try:
                index = app_values.index(str(raw))
            except ValueError:
                return None
            return round((index + 1) * 100 / len(app_values))
        return percentage_for_property(self._speed, raw)

    @property
    def speed_count(self) -> int:
        """Return the number of distinct speed steps."""
        if self._speed is None:
            return 0
        if app_values := self._app_manual_speed_values:
            return len(app_values)
        if numeric_range := self._speed.numeric_range:
            minimum, maximum, step = numeric_range
            return max(1, round((maximum - minimum) / step) + 1)
        return len(self._speed.enum_options)

    @property
    def preset_modes(self) -> list[str] | None:
        """Return mode labels reported by the TSL."""
        if not self._mode:
            return None
        return list(self._mode.enum_options.values()) or None

    @property
    def preset_mode(self) -> str | None:
        """Return the active mode label."""
        if not self._mode:
            return None
        return self._mode.option_for_value(
            self.property_value(self._mode.identifier)
        )

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **_kwargs: Any,
    ) -> None:
        """Turn on the purifier and optionally set speed or mode."""
        self.ensure_app_control_allowed(require_power=False)
        items: dict[str, Any] = {}
        if self._power:
            items[self._power.identifier] = self._power.coerce_value(1)
        if percentage is not None and self._speed:
            items[self._speed.identifier] = self._raw_speed(percentage)
        if preset_mode is not None and self._mode:
            value = self._mode.value_for_option(preset_mode)
            if value is not None:
                items[self._mode.identifier] = self._mode.coerce_value(value)
        if items:
            await self.coordinator.async_set_properties(self.device.iot_id, items)

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn off the purifier."""
        self.ensure_app_control_allowed(require_power=False)
        if self._power:
            await self.coordinator.async_set_properties(
                self.device.iot_id,
                {self._power.identifier: self._power.coerce_value(0)},
            )

    async def async_set_percentage(self, percentage: int) -> None:
        """Set purifier fan speed."""
        if percentage <= 0:
            await self.async_turn_off()
            return
        self.ensure_app_control_allowed(require_power=True)
        if not self._speed:
            return
        items = {self._speed.identifier: self._raw_speed(percentage)}
        if self._power:
            items[self._power.identifier] = self._power.coerce_value(1)
        await self.coordinator.async_set_properties(self.device.iot_id, items)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set a TSL-defined purifier mode."""
        self.ensure_app_control_allowed(require_power=True)
        if not self._mode:
            return
        raw = self._mode.value_for_option(preset_mode)
        if raw is None:
            raise ValueError(f"Unsupported preset mode: {preset_mode}")
        items = {
            self._mode.identifier: self._mode.coerce_value(raw),
        }
        if self._power:
            items[self._power.identifier] = self._power.coerce_value(1)
        await self.coordinator.async_set_properties(self.device.iot_id, items)

    def _raw_speed(self, percentage: int) -> Any:
        speed = self._speed
        if speed is None:
            return None
        if app_values := self._app_manual_speed_values:
            index = min(
                len(app_values) - 1,
                max(0, math.ceil(percentage * len(app_values) / 100) - 1),
            )
            return speed.coerce_value(app_values[index])
        return value_for_percentage(speed, percentage)

    @property
    def _app_manual_speed_values(self) -> list[str] | None:
        """Return the five XDJ gear values, excluding its separate auto mode."""
        speed = self._speed
        if (
            speed is None
            or self.device.product_category != "KX"
            or speed.identifier.casefold() != "windspeed"
        ):
            return None
        values = list(speed.enum_options)
        if len(values) > 1 and values[0] == "0":
            return values[1:]
        return None

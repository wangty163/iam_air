"""Fan platform for IAM air purifiers."""

from __future__ import annotations

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
        return percentage_for_property(self._speed, raw)

    @property
    def speed_count(self) -> int:
        """Return the number of distinct speed steps."""
        if self._speed is None:
            return 0
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
        if not self._speed:
            return
        items = {self._speed.identifier: self._raw_speed(percentage)}
        if self._power:
            items[self._power.identifier] = self._power.coerce_value(1)
        await self.coordinator.async_set_properties(self.device.iot_id, items)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set a TSL-defined purifier mode."""
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
        return value_for_percentage(speed, percentage)

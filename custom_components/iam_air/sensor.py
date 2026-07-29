"""Sensor platform for IAM air purifiers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    PERCENTAGE,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IamAirConfigEntry
from .entity import IamAirEntity, add_iam_entities
from .models import IamAirDevice, TslProperty


@dataclass(frozen=True, slots=True)
class IamSensorSpec:
    """Known air-purifier measurement."""

    aliases: tuple[str, ...]
    device_class: SensorDeviceClass | None = None
    default_unit: str | None = None
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT


SENSOR_SPECS = (
    IamSensorSpec(
        aliases=("PM25", "pm25"),
        device_class=SensorDeviceClass.PM25,
        default_unit=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    ),
    IamSensorSpec(aliases=("HCHO", "hcho", "formaldehyde")),
    IamSensorSpec(aliases=("HCHOLevel", "hchoLevel"), state_class=None),
    IamSensorSpec(aliases=("TVOC", "tvoc")),
    IamSensorSpec(aliases=("TVOCLevel", "tvocLevel"), state_class=None),
    IamSensorSpec(aliases=("PM25Level", "pm25Level"), state_class=None),
    IamSensorSpec(
        aliases=("CuTemperature", "CurrentTemperature", "currentTemp"),
        device_class=SensorDeviceClass.TEMPERATURE,
        default_unit=UnitOfTemperature.CELSIUS,
    ),
    IamSensorSpec(
        aliases=("CurrentHumidity", "currentHumidity", "humidity"),
        device_class=SensorDeviceClass.HUMIDITY,
        default_unit=PERCENTAGE,
    ),
    IamSensorSpec(
        aliases=("FilterRunTime_1", "filterRunTime_1"),
        device_class=SensorDeviceClass.DURATION,
        default_unit=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    IamSensorSpec(
        aliases=("FilterRunTime_2", "filterRunTime_2"),
        device_class=SensorDeviceClass.DURATION,
        default_unit=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    IamSensorSpec(
        aliases=("Runtime_1", "runtime_1"),
        device_class=SensorDeviceClass.DURATION,
        default_unit=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    IamSensorSpec(
        aliases=("FilterStatus_1", "filterStatusOne", "FilterStatus"),
        state_class=None,
    ),
    IamSensorSpec(
        aliases=("FilterStatus_2", "filterStatusTwo"),
        state_class=None,
    ),
    IamSensorSpec(
        aliases=("FilterStatus_3", "filterStatusThree"),
        state_class=None,
    ),
    IamSensorSpec(
        aliases=("TimingRemain", "timingRemain"),
        device_class=SensorDeviceClass.DURATION,
        default_unit=UnitOfTime.MINUTES,
    ),
    IamSensorSpec(
        aliases=("airQualityGrade", "airQuality"),
        state_class=None,
    ),
    IamSensorSpec(
        aliases=("errorCode", "ErrorCode"),
        state_class=None,
    ),
)

FILTER_RUNTIME_ALIASES = (
    ("FilterRunTime_1", "filterRunTime_1"),
    ("FilterRunTime_2", "filterRunTime_2"),
)


async def async_setup_entry(
    _hass: Any,
    entry: IamAirConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up available purifier sensors."""
    coordinator = entry.runtime_data.coordinator
    entities: list[IamAirSensor] = []
    for device in coordinator.devices.values():
        seen: set[str] = set()
        for spec in SENSOR_SPECS:
            prop = device.find_property(*spec.aliases)
            if not prop or not prop.readable or prop.identifier in seen:
                continue
            seen.add(prop.identifier)
            entities.append(IamAirSensor(coordinator, device, prop=prop, spec=spec))
        for index, (aliases, maximum) in enumerate(
            zip(
                FILTER_RUNTIME_ALIASES,
                device.filter_max_runtimes,
                strict=True,
            ),
            start=1,
        ):
            prop = device.find_property(*aliases)
            if prop is None or not prop.readable or maximum is None:
                continue
            entities.append(
                IamAirFilterLifeSensor(
                    coordinator,
                    device,
                    prop=prop,
                    filter_index=index,
                    maximum_runtime=maximum,
                )
            )
    add_iam_entities(entry, async_add_entities, entities)


class IamAirSensor(IamAirEntity, SensorEntity):
    """A sensor backed by one TSL property."""

    def __init__(
        self,
        coordinator: Any,
        device: IamAirDevice,
        *,
        prop: TslProperty,
        spec: IamSensorSpec,
    ) -> None:
        super().__init__(
            coordinator,
            device,
            unique_suffix=prop.identifier.lower(),
        )
        self._property = prop
        self._attr_name = prop.name
        self._attr_device_class = spec.device_class
        self._attr_native_unit_of_measurement = normalize_unit(
            prop.unit or spec.default_unit
        )
        self._attr_state_class = spec.state_class

    @property
    def native_value(self) -> Any:
        """Return the latest property value."""
        value = self.property_value(self._property.identifier)
        if value is None:
            return None
        return self._property.option_for_value(value) or value


class IamAirFilterLifeSensor(IamAirEntity, SensorEntity):
    """Remaining filter lifetime calculated with the App's model limit."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: Any,
        device: IamAirDevice,
        *,
        prop: TslProperty,
        filter_index: int,
        maximum_runtime: int,
    ) -> None:
        super().__init__(
            coordinator,
            device,
            unique_suffix=f"filter_life_{filter_index}",
        )
        self._property = prop
        self._maximum_runtime = maximum_runtime
        self._attr_name = f"滤芯{filter_index}剩余寿命"

    @property
    def native_value(self) -> int | None:
        """Return the App-equivalent remaining lifetime percentage."""
        return filter_life_percentage(
            self.property_value(self._property.identifier),
            self._maximum_runtime,
        )


def filter_life_percentage(used_runtime: Any, maximum_runtime: Any) -> int | None:
    """Calculate App-equivalent remaining filter lifetime, clamped to 0-100."""
    try:
        used = float(used_runtime)
        maximum = float(maximum_runtime)
    except (TypeError, ValueError):
        return None
    if maximum <= 0:
        return None
    remaining = (maximum - used) / maximum * 100
    return min(100, max(0, math.floor(remaining + 0.5)))


def normalize_unit(unit: str | None) -> str | None:
    """Normalize common TSL unit spellings for Home Assistant."""
    if unit is None:
        return None
    compact = unit.strip().lower().replace(" ", "")
    if compact in {"ug/m3", "ug/m³", "μg/m3", "μg/m³", "µg/m3", "µg/m³"}:
        return CONCENTRATION_MICROGRAMS_PER_CUBIC_METER
    if compact in {"c", "°c", "℃"}:
        return UnitOfTemperature.CELSIUS
    if compact in {"%", "%rh", "rh%"}:
        return PERCENTAGE
    return unit

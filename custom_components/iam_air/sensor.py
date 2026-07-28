"""Sensor platform for IAM air purifiers."""

from __future__ import annotations

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
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IamAirConfigEntry
from .entity import IamAirEntity
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
    IamSensorSpec(aliases=("HCHOLevel", "hchoLevel")),
    IamSensorSpec(aliases=("TVOC", "tvoc")),
    IamSensorSpec(aliases=("TVOCLevel", "tvocLevel")),
    IamSensorSpec(aliases=("PM25Level", "pm25Level")),
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
        aliases=("filterStatusOne", "FilterStatus", "filterStatus"),
        default_unit=PERCENTAGE,
    ),
    IamSensorSpec(
        aliases=("filterStatusTwo", "FilterStatus_2"),
        default_unit=PERCENTAGE,
    ),
    IamSensorSpec(
        aliases=("filterStatusThree", "FilterStatus_3"),
        default_unit=PERCENTAGE,
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
    async_add_entities(entities)


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
        return self.value(self._property.identifier)


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

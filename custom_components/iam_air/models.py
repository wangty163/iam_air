"""Protocol models and TSL helpers for IAM Air."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

from .const import (
    MODE_PROPERTY_ALIASES,
    POWER_PROPERTY_ALIASES,
    SPEED_PROPERTY_ALIASES,
)


@dataclass(frozen=True, slots=True)
class IamAccountSession:
    """Authenticated IAM account details."""

    user_id: str
    username: str


@dataclass(frozen=True, slots=True)
class IotSession:
    """Alibaba IoT session details."""

    iot_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    identity_id: str = field(repr=False)
    expires_in: int
    created_at: float


@dataclass(frozen=True, slots=True)
class TslProperty:
    """One property from an Alibaba Thing Specification Language document."""

    identifier: str
    name: str
    access_mode: str
    data_type: str
    specs: Any = None
    unit: str | None = None

    @property
    def readable(self) -> bool:
        """Return whether the property can be read."""
        return "r" in self.access_mode.lower()

    @property
    def writable(self) -> bool:
        """Return whether the property can be written."""
        return "w" in self.access_mode.lower()

    @property
    def enum_options(self) -> dict[str, str]:
        """Return raw enum values mapped to human-readable labels."""
        if isinstance(self.specs, dict):
            return {str(value): str(label) for value, label in self.specs.items()}
        if isinstance(self.specs, list):
            options: dict[str, str] = {}
            for item in self.specs:
                if not isinstance(item, dict):
                    continue
                value = item.get("value")
                label = item.get("name", item.get("label", value))
                if value is not None:
                    options[str(value)] = str(label)
            return options
        return {}

    @property
    def numeric_range(self) -> tuple[float, float, float] | None:
        """Return min, max and step for numeric properties."""
        if not isinstance(self.specs, dict):
            return None
        try:
            minimum = float(self.specs["min"])
            maximum = float(self.specs["max"])
            step = float(self.specs.get("step", 1))
        except KeyError, TypeError, ValueError:
            return None
        if maximum <= minimum or step <= 0:
            return None
        return minimum, maximum, step

    def option_for_value(self, value: Any) -> str | None:
        """Translate a raw enum value to a label."""
        return self.enum_options.get(str(value))

    def value_for_option(self, option: str) -> str | None:
        """Translate an enum label back to its raw value."""
        for value, label in self.enum_options.items():
            if label == option:
                return value
        return None

    def coerce_value(self, value: Any) -> Any:
        """Coerce a UI value to the primitive expected by the TSL."""
        if self.data_type in {"bool", "enum", "int"}:
            try:
                return int(value)
            except TypeError, ValueError:
                return value
        if self.data_type in {"double", "float"}:
            try:
                return float(value)
            except TypeError, ValueError:
                return value
        return value


@dataclass(frozen=True, slots=True)
class IamAirDevice:
    """A discovered IAM air purifier."""

    iot_id: str
    name: str
    model: str
    product_key: str
    device_name: str
    online: bool
    properties: dict[str, TslProperty] = field(default_factory=dict)

    def find_property(self, *aliases: str) -> TslProperty | None:
        """Find a TSL property without depending on identifier case."""
        by_lower = {
            identifier.lower(): prop for identifier, prop in self.properties.items()
        }
        for alias in aliases:
            if prop := by_lower.get(alias.lower()):
                return prop
        return None

    @property
    def looks_like_air_purifier(self) -> bool:
        """Return whether the TSL exposes an air-purifier control surface."""
        has_power = self.find_property(*POWER_PROPERTY_ALIASES) is not None
        has_speed = self.find_property(*SPEED_PROPERTY_ALIASES) is not None
        has_mode = self.find_property(*MODE_PROPERTY_ALIASES) is not None
        has_air_sensor = self.find_property(
            "PM25", "pm25", "HCHO", "hcho", "tvoc", "airQualityGrade"
        )
        return has_power and (has_speed or has_mode or has_air_sensor is not None)


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    """Latest property snapshot for a device."""

    properties: dict[str, Any]
    available: bool = True


def value_as_bool(value: Any) -> bool:
    """Interpret common Link Living boolean representations."""
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "off", "no"}
    return bool(value)


def percentage_for_property(prop: TslProperty, value: Any) -> int | None:
    """Convert a numeric or enum TSL value to a non-zero fan percentage."""
    if numeric_range := prop.numeric_range:
        minimum, maximum, step = numeric_range
        count = max(1, round((maximum - minimum) / step) + 1)
        try:
            index = round((float(value) - minimum) / step)
        except TypeError, ValueError:
            return None
        index = min(count - 1, max(0, index))
        return round((index + 1) * 100 / count)
    options = list(prop.enum_options)
    try:
        index = options.index(str(value))
    except ValueError:
        return None
    return round((index + 1) * 100 / len(options))


def value_for_percentage(prop: TslProperty, percentage: int) -> Any:
    """Convert a Home Assistant fan percentage to a valid TSL value."""
    percentage = max(1, min(100, percentage))
    if numeric_range := prop.numeric_range:
        minimum, maximum, step = numeric_range
        count = max(1, round((maximum - minimum) / step) + 1)
        index = min(
            count - 1,
            max(0, math.ceil(percentage * count / 100) - 1),
        )
        return prop.coerce_value(minimum + index * step)
    options = list(prop.enum_options)
    if not options:
        return prop.coerce_value(percentage)
    index = min(
        len(options) - 1,
        max(0, math.ceil(percentage * len(options) / 100) - 1),
    )
    return prop.coerce_value(options[index])


def parse_tsl(data: Any) -> dict[str, TslProperty]:
    """Parse the different TSL response shapes used by Link Living."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return {}
    if not isinstance(data, dict):
        return {}

    if "properties" not in data and "data" in data:
        return parse_tsl(data["data"])
    properties = data.get("properties", [])
    if not isinstance(properties, list):
        return {}

    parsed: dict[str, TslProperty] = {}
    for raw in properties:
        if not isinstance(raw, dict):
            continue
        identifier = raw.get("identifier")
        if not identifier:
            continue
        data_type = raw.get("dataType") or {}
        if not isinstance(data_type, dict):
            data_type = {}
        specs = data_type.get("specs")
        unit = None
        if isinstance(specs, dict):
            unit_value = specs.get("unit")
            unit = str(unit_value) if unit_value else None
        parsed[str(identifier)] = TslProperty(
            identifier=str(identifier),
            name=str(raw.get("name") or identifier),
            access_mode=str(raw.get("accessMode") or "r"),
            data_type=str(data_type.get("type") or "unknown").lower(),
            specs=specs,
            unit=unit,
        )
    return parsed


def parse_device(raw: dict[str, Any], tsl: Any) -> IamAirDevice:
    """Create a device model from binding-list data and its TSL."""
    iot_id = str(raw.get("iotId") or "")
    name = str(
        raw.get("nickName") or raw.get("devName") or raw.get("deviceName") or "IAM Air"
    )
    return IamAirDevice(
        iot_id=iot_id,
        name=name,
        model=str(raw.get("productName") or raw.get("categoryName") or "IAM Air"),
        product_key=str(raw.get("productKey") or ""),
        device_name=str(raw.get("deviceName") or ""),
        online=raw.get("status") in (1, "1", True, "online", "ONLINE"),
        properties=parse_tsl(tsl),
    )

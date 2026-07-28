"""Tests for purifier sensor metadata."""

from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    PERCENTAGE,
    UnitOfTemperature,
)

from custom_components.iam_air.models import TslProperty
from custom_components.iam_air.sensor import normalize_unit


def test_normalize_unit() -> None:
    """Known vendor unit spellings map to Home Assistant units."""
    assert normalize_unit("ug/m3") == CONCENTRATION_MICROGRAMS_PER_CUBIC_METER
    assert normalize_unit("μg/m³") == CONCENTRATION_MICROGRAMS_PER_CUBIC_METER
    assert normalize_unit("℃") == UnitOfTemperature.CELSIUS
    assert normalize_unit("%RH") == PERCENTAGE
    assert normalize_unit("mg/m³") == "mg/m³"


def test_enum_sensor_value_uses_app_label() -> None:
    """Enum helpers expose the App's readable status labels."""
    prop = TslProperty(
        identifier="FilterStatus_1",
        name="滤芯寿命状态_1",
        access_mode="r",
        data_type="enum",
        specs={"0": "正常", "1": "需要更换"},
    )

    assert prop.option_for_value(0) == "正常"

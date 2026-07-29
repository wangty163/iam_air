"""Tests for purifier sensor metadata."""

from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    PERCENTAGE,
    UnitOfTemperature,
)

from custom_components.iam_air.models import TslProperty
from custom_components.iam_air.sensor import filter_life_percentage, normalize_unit


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


def test_filter_life_percentage_matches_app_formula() -> None:
    """Remaining lifetime uses the Android App's rounded percentage formula."""
    assert filter_life_percentage(207, 3000) == 93
    assert filter_life_percentage(89, 9000) == 99
    assert filter_life_percentage(3000, 3000) == 0
    assert filter_life_percentage(-10, 3000) == 100
    assert filter_life_percentage(4000, 3000) == 0


def test_filter_life_percentage_rejects_invalid_limits() -> None:
    """Missing runtime data or nonpositive limits remain unavailable."""
    assert filter_life_percentage(None, 3000) is None
    assert filter_life_percentage(100, 0) is None
    assert filter_life_percentage("invalid", 3000) is None

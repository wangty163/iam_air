"""Tests for purifier sensor metadata."""

from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    PERCENTAGE,
    UnitOfTemperature,
)

from custom_components.iam_air.sensor import normalize_unit


def test_normalize_unit() -> None:
    """Known vendor unit spellings map to Home Assistant units."""
    assert normalize_unit("ug/m3") == CONCENTRATION_MICROGRAMS_PER_CUBIC_METER
    assert normalize_unit("μg/m³") == CONCENTRATION_MICROGRAMS_PER_CUBIC_METER
    assert normalize_unit("℃") == UnitOfTemperature.CELSIUS
    assert normalize_unit("%RH") == PERCENTAGE
    assert normalize_unit("mg/m³") == "mg/m³"

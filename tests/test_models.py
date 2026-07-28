"""Tests for TSL and device models."""

from custom_components.iam_air.models import (
    TslProperty,
    parse_device,
    parse_tsl,
    percentage_for_property,
    value_as_bool,
    value_for_percentage,
)

TSL = {
    "properties": [
        {
            "identifier": "powerstate",
            "name": "Power",
            "accessMode": "rw",
            "dataType": {"type": "bool", "specs": {"0": "Off", "1": "On"}},
        },
        {
            "identifier": "windspeed",
            "name": "Fan speed",
            "accessMode": "rw",
            "dataType": {
                "type": "int",
                "specs": {"min": "1", "max": "5", "step": "1"},
            },
        },
        {
            "identifier": "mode",
            "name": "Mode",
            "accessMode": "rw",
            "dataType": {
                "type": "enum",
                "specs": {"0": "Automatic", "1": "Sleep"},
            },
        },
        {
            "identifier": "PM25",
            "name": "PM2.5",
            "accessMode": "r",
            "dataType": {"type": "int", "specs": {"unit": "µg/m³"}},
        },
    ]
}


def test_parse_tsl_and_detect_air_purifier() -> None:
    """A live-style TSL creates a purifier model without a product-key list."""
    device = parse_device(
        {
            "iotId": "fake-device-id",
            "nickName": "Living room purifier",
            "productName": "M8",
            "status": 1,
        },
        TSL,
    )

    assert device.looks_like_air_purifier
    assert device.find_property("POWERSTATE").identifier == "powerstate"
    assert device.find_property("PM25").unit == "µg/m³"


def test_enum_and_numeric_specs() -> None:
    """TSL enum labels and numeric ranges round-trip."""
    properties = parse_tsl(TSL)

    assert properties["mode"].option_for_value(1) == "Sleep"
    assert properties["mode"].value_for_option("Automatic") == "0"
    assert properties["mode"].coerce_value("1") == 1
    assert properties["windspeed"].numeric_range == (1.0, 5.0, 1.0)


def test_parse_invalid_tsl_is_empty() -> None:
    """Malformed TSL data cannot create writable properties."""
    assert parse_tsl(None) == {}
    assert parse_tsl({"properties": "not-a-list"}) == {}


def test_value_as_bool_handles_string_zero() -> None:
    """Cloud string values use semantic boolean conversion."""
    assert not value_as_bool("0")
    assert not value_as_bool("false")
    assert value_as_bool("1")
    assert value_as_bool(1)


def test_list_form_enum_specs() -> None:
    """Newer list-shaped enum specs are supported."""
    prop = TslProperty(
        identifier="mode",
        name="Mode",
        access_mode="rw",
        data_type="enum",
        specs=[
            {"value": 0, "name": "Automatic"},
            {"value": 1, "name": "Sleep"},
        ],
    )

    assert prop.enum_options == {"0": "Automatic", "1": "Sleep"}


def test_numeric_speed_percentage_uses_discrete_steps() -> None:
    """Fan speed 1 of 5 is represented as 20%, not as off."""
    speed = parse_tsl(TSL)["windspeed"]

    assert percentage_for_property(speed, 1) == 20
    assert percentage_for_property(speed, 5) == 100
    assert value_for_percentage(speed, 1) == 1
    assert value_for_percentage(speed, 20) == 1
    assert value_for_percentage(speed, 21) == 2


def test_parse_nested_json_string_tsl() -> None:
    """The documented string-shaped TSL response remains supported."""
    import json

    parsed = parse_tsl({"data": json.dumps(TSL)})

    assert "powerstate" in parsed

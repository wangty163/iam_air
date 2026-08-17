"""Tests for TSL and device models."""

from custom_components.iam_air.models import (
    TslProperty,
    parse_app_power_status,
    parse_device,
    parse_device_online,
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


def test_parse_device_online_is_tristate() -> None:
    """Known online and offline values parse without guessing unknown values."""
    assert parse_device_online(1) is True
    assert parse_device_online("ONLINE") is True
    for value in (
        0,
        3,
        8,
        "3",
        "offline",
        "inactive",
        "disabled",
    ):
        assert parse_device_online(value) is False
    assert parse_device_online(None) is None
    assert parse_device_online(2) is None


def test_parse_app_power_status_keeps_offline_separate_from_power() -> None:
    """The App homepage exposes offline, online-off and online-on states."""
    assert parse_app_power_status(0) is False
    assert parse_app_power_status("0") is False
    for value in (1, 2, "1", "2"):
        assert parse_app_power_status(value) is True
    for value in (None, True, False, 3, "online", "offline", ""):
        assert parse_app_power_status(value) is None


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


def test_parse_device_online_is_strict_and_tri_state() -> None:
    """Only documented Link Living status values decide connectivity."""
    assert parse_device_online(1) is True
    assert parse_device_online("online") is True
    assert parse_device_online(0) is False
    assert parse_device_online("8") is False
    assert parse_device_online(2) is None
    assert parse_device_online("unexpected") is None


def test_parse_app_power_status_does_not_treat_booleans_as_device_state() -> None:
    """FOG App power status keeps unknown values distinct from offline."""
    assert parse_app_power_status(0) is False
    assert parse_app_power_status("1") is True
    assert parse_app_power_status(2) is True
    assert parse_app_power_status(True) is None
    assert parse_app_power_status("unexpected") is None

"""Tests for TSL and device models."""

from custom_components.iam_air.models import (
    TslProperty,
    parse_device,
    parse_tsl,
    percentage_for_property,
    select_app_device_metadata,
    select_app_filter_names,
    select_filter_max_runtimes,
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


def test_app_display_name_overrides_cloud_device_identifier() -> None:
    """The name rendered by the App wins over a machine-generated device name."""
    device = parse_device(
        {
            "iotId": "fake-device-id",
            "deviceName": "machinegenerated12345",
            "productName": "M8",
            "status": 1,
        },
        TSL,
        display_name="Living room purifier",
    )

    assert device.name == "Living room purifier"


def test_app_detail_uses_product_type_when_device_has_no_custom_name() -> None:
    """The precise App product type replaces a generic default product name."""
    display_name, model_name = select_app_device_metadata(
        {"productName": "Homepage default"},
        {
            "productName": "Default purifier",
            "defaultProductName": "Default purifier",
            "productTypeName": "IAM M8 purifier",
        },
    )

    assert display_name == "IAM M8 purifier"
    assert model_name == "IAM M8 purifier"


def test_app_detail_preserves_user_custom_device_name() -> None:
    """A device note set by the user remains the primary display name."""
    display_name, model_name = select_app_device_metadata(
        {"productName": "Homepage name"},
        {
            "productName": "Living room purifier",
            "defaultProductName": "Default purifier",
            "productTypeName": "IAM M8 purifier",
        },
    )

    assert display_name == "Living room purifier"
    assert model_name == "IAM M8 purifier"


def test_filter_max_runtimes_match_app_category_and_type() -> None:
    """Filter lifetime limits come from the exact App model configuration."""
    result = select_filter_max_runtimes(
        {"productCategory": "KX", "productType": "5"},
        [
            {
                "productCategory": "KX",
                "productType": "4",
                "filterMaxRuntime": 1000,
                "filter2MaxRuntime": 2000,
            },
            {
                "productCategory": "KX",
                "productType": "5",
                "filterMaxRuntime": 3000,
                "filter2MaxRuntime": 9000,
            },
        ],
    )

    assert result == (3000, 9000)


def test_filter_max_runtimes_reject_missing_or_nonpositive_values() -> None:
    """Invalid model limits cannot create misleading percentage sensors."""
    result = select_filter_max_runtimes(
        {"productCategory": "KX", "productType": 5},
        [
            {
                "productCategory": "KX",
                "productType": "5",
                "filterMaxRuntime": 0,
                "filter2MaxRuntime": "invalid",
            }
        ],
    )

    assert result == (None, None)


def test_app_filter_names_match_xdj_dual_filter_titles() -> None:
    """KX dual-filter devices use the two static titles rendered by the App."""
    assert select_app_filter_names(
        {"productCategory": "KX", "productType": "5"},
        (3000, 9000),
    ) == ("HEPA", "炭魔方")
    assert select_app_filter_names(
        {"productCategory": "KX", "productType": "2"},
        (3000, None),
    ) == ("滤网", None)


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

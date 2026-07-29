"""Tests for the XDJ/Y control surface used by the IAM App."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.fan import FanEntityFeature
from homeassistant.exceptions import HomeAssistantError

from custom_components.iam_air.button import IamAirFilterResetButton
from custom_components.iam_air.entity import app_property_name
from custom_components.iam_air.fan import IamAirFan
from custom_components.iam_air.models import DeviceSnapshot, TslProperty, parse_device
from custom_components.iam_air.number import IamAirNumber
from custom_components.iam_air.select import IamAirSelect
from custom_components.iam_air.switch import IamAirSwitch


def make_device_and_coordinator():
    """Build one exact-name XDJ/Y device and coordinator stub."""
    tsl = {
        "properties": [
            {
                "identifier": "PowerSwitch",
                "name": "电源开关",
                "accessMode": "rw",
                "dataType": {
                    "type": "bool",
                    "specs": {"0": "关闭", "1": "开启"},
                },
            },
            {
                "identifier": "WindSpeed",
                "name": "风速",
                "accessMode": "rw",
                "dataType": {
                    "type": "enum",
                    "specs": {
                        "0": "自动",
                        "1": "静音档",
                        "2": "低档",
                        "3": "中档",
                        "4": "高档",
                        "5": "最高档",
                    },
                },
            },
            {
                "identifier": "WorkMode",
                "name": "工作模式",
                "accessMode": "rw",
                "dataType": {
                    "type": "enum",
                    "specs": {"0": "自动", "1": "手动", "2": "睡眠"},
                },
            },
            {
                "identifier": "ScreenSwitch",
                "name": "屏幕显示开关",
                "accessMode": "rw",
                "dataType": {
                    "type": "bool",
                    "specs": {"0": "关闭", "1": "开启"},
                },
            },
            {
                "identifier": "TimingOff",
                "name": "定时关机设置",
                "accessMode": "rw",
                "dataType": {
                    "type": "int",
                    "specs": {"min": "0", "max": "12", "step": "1"},
                },
            },
            {
                "identifier": "FilterReset",
                "name": "滤芯使用时间复位",
                "accessMode": "rw",
                "dataType": {
                    "type": "enum",
                    "specs": {
                        "1": "滤芯1使用时间复位",
                        "2": "滤芯2使用时间复位",
                    },
                },
            },
        ]
    }
    device = parse_device(
        {
            "iotId": "fake-device-id",
            "nickName": "Purifier",
            "productName": "Y",
            "status": 1,
        },
        tsl,
        product_category="KX",
        product_type="5",
        filter_names=("HEPA", "炭魔方"),
    )
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.async_set_properties = AsyncMock()
    coordinator.data = {
        device.iot_id: DeviceSnapshot(
            properties={
                "PowerSwitch": 1,
                "WindSpeed": 2,
                "WorkMode": 1,
                "ScreenSwitch": 1,
                "TimingOff": 0,
                "FilterReset": 2,
            }
        )
    }
    return device, coordinator


async def test_fan_exposes_power_five_gears_and_three_modes() -> None:
    """The primary fan exposes the same core controls as the App."""
    device, coordinator = make_device_and_coordinator()
    fan = IamAirFan(coordinator, device)

    assert fan.is_on
    assert fan.speed_count == 5
    assert fan.percentage == 40
    assert fan.preset_modes == ["自动", "手动", "睡眠"]
    assert fan.preset_mode == "手动"
    assert fan.supported_features & FanEntityFeature.TURN_ON
    assert fan.supported_features & FanEntityFeature.TURN_OFF

    await fan.async_set_percentage(100)
    coordinator.async_set_properties.assert_awaited_once_with(
        "fake-device-id",
        {"WindSpeed": 5, "PowerSwitch": 1},
    )

    coordinator.async_set_properties.reset_mock()
    await fan.async_turn_off()
    await fan.async_turn_on()
    assert coordinator.async_set_properties.await_args_list[0].args == (
        "fake-device-id",
        {"PowerSwitch": 0},
    )
    assert coordinator.async_set_properties.await_args_list[1].args == (
        "fake-device-id",
        {"PowerSwitch": 1},
    )


async def test_explicit_switch_and_select_controls_write_raw_values() -> None:
    """Named switch and select entities remain easy to automate."""
    device, coordinator = make_device_and_coordinator()
    power = IamAirSwitch(
        coordinator,
        device,
        device.properties["PowerSwitch"],
    )
    speed = IamAirSelect(
        coordinator,
        device,
        device.properties["WindSpeed"],
    )

    assert power.is_on
    assert speed.current_option == "低档"
    assert speed.options == ["自动", "静音档", "低档", "中档", "高档", "最高档"]

    await power.async_turn_off()
    await speed.async_select_option("最高档")
    assert coordinator.async_set_properties.await_args_list[0].args == (
        "fake-device-id",
        {"PowerSwitch": 0},
    )
    assert coordinator.async_set_properties.await_args_list[1].args == (
        "fake-device-id",
        {"WindSpeed": 5},
    )


async def test_kx_type_5_screen_turn_on_leaves_sleep_mode_first() -> None:
    """The App sends the current screen value, then exits sleep mode."""
    device, coordinator = make_device_and_coordinator()
    screen = IamAirSwitch(
        coordinator,
        device,
        device.properties["ScreenSwitch"],
    )
    coordinator.data[device.iot_id].properties.update(
        {
            "PowerSwitch": 1,
            "ScreenSwitch": 0,
            "T_Panel_Status": 0,
            "Trusteeship": 0,
            "WorkMode": 2,
        }
    )

    assert not screen.is_on
    await screen.async_turn_on()

    assert coordinator.async_set_properties.await_args_list[0].args == (
        "fake-device-id",
        {"ScreenSwitch": 0},
    )
    assert coordinator.async_set_properties.await_args_list[0].kwargs == {
        "optimistic_items": {"ScreenSwitch": 1}
    }
    assert coordinator.async_set_properties.await_args_list[1].args == (
        "fake-device-id",
        {"WorkMode": 0},
    )


async def test_kx_type_5_screen_uses_panel_state_during_trusteeship() -> None:
    """The App toggles the visible panel state even during trusteeship."""
    device, coordinator = make_device_and_coordinator()
    screen = IamAirSwitch(
        coordinator,
        device,
        device.properties["ScreenSwitch"],
    )
    coordinator.data[device.iot_id].properties.update(
        {
            "PowerSwitch": 1,
            "ScreenSwitch": 0,
            "T_Panel_Status": 1,
            "Trusteeship": 1,
            "WorkMode": 1,
        }
    )

    assert screen.is_on
    assert screen.extra_state_attributes == {"app_action": "息屏"}
    await screen.async_turn_off()
    coordinator.async_set_properties.assert_awaited_once_with(
        "fake-device-id",
        {"ScreenSwitch": 1},
        optimistic_items={"ScreenSwitch": 0, "T_Panel_Status": 0},
    )


async def test_kx_type_5_screen_matches_app_state_outside_trusteeship() -> None:
    """The App state remains actionable when panel telemetry disagrees."""
    device, coordinator = make_device_and_coordinator()
    screen = IamAirSwitch(
        coordinator,
        device,
        device.properties["ScreenSwitch"],
    )
    coordinator.data[device.iot_id].properties.update(
        {
            "PowerSwitch": 1,
            "ScreenSwitch": 0,
            "T_Panel_Status": 1,
            "Trusteeship": 0,
            "WorkMode": 1,
        }
    )

    assert not screen.is_on
    await screen.async_turn_on()
    coordinator.async_set_properties.assert_awaited_once_with(
        "fake-device-id",
        {"ScreenSwitch": 0},
        optimistic_items={"ScreenSwitch": 1},
    )

    coordinator.data[device.iot_id].properties.update(
        {
            "ScreenSwitch": 1,
            "T_Panel_Status": 0,
        }
    )
    assert screen.is_on


async def test_app_blocks_main_controls_during_trusteeship() -> None:
    """Power, speed and modes follow the App's smart-trusteeship guard."""
    device, coordinator = make_device_and_coordinator()
    coordinator.data[device.iot_id].properties["Trusteeship"] = 1
    fan = IamAirFan(coordinator, device)
    speed = IamAirSelect(
        coordinator,
        device,
        device.properties["WindSpeed"],
    )

    with pytest.raises(HomeAssistantError, match="智能托管"):
        await fan.async_turn_off()
    with pytest.raises(HomeAssistantError, match="智能托管"):
        await speed.async_select_option("最高档")
    coordinator.async_set_properties.assert_not_awaited()


async def test_timer_number_and_filter_reset_button() -> None:
    """Timer and maintenance entities preserve exact TSL values."""
    device, coordinator = make_device_and_coordinator()
    timer = IamAirNumber(
        coordinator,
        device,
        prop=device.properties["TimingOff"],
        default_unit="h",
    )
    reset = IamAirFilterResetButton(
        coordinator,
        device,
        prop=device.properties["FilterReset"],
        raw_value="1",
        label="滤芯1使用时间复位",
    )

    assert timer.native_min_value == 0
    assert timer.native_max_value == 12
    assert timer.native_step == 1
    assert timer.native_value == 0
    assert timer.state == 0

    await timer.async_set_native_value(3)
    await reset.async_press()
    assert coordinator.async_set_properties.await_args_list[0].args == (
        "fake-device-id",
        {"TimingOff": 3},
    )
    assert coordinator.async_set_properties.await_args_list[1].args == (
        "fake-device-id",
        {"FilterReset": 1},
    )


def test_app_entity_names_include_filter_titles_and_device_page_labels() -> None:
    """HA entity names follow the visible XDJ page instead of raw TSL labels."""
    device, _coordinator = make_device_and_coordinator()
    assert app_property_name(device, device.properties["PowerSwitch"]) == "电源"
    filter_runtime = TslProperty(
        identifier="FilterRunTime_1",
        name="滤芯使用时间",
        access_mode="r",
        data_type="int",
    )
    assert app_property_name(device, filter_runtime) == "HEPA累计使用时间"


def test_trusteeship_controls_use_app_picker_ranges() -> None:
    """HA offers the narrower threshold choices present in the App."""
    device, coordinator = make_device_and_coordinator()
    hcho = TslProperty(
        identifier="T_ON_HCHO",
        name="raw",
        access_mode="rw",
        data_type="double",
        specs={"min": "0", "max": "0.2", "step": "0.02"},
        unit="mg/m³",
    )
    voc = TslProperty(
        identifier="T_ON_TVOCLevel",
        name="raw",
        access_mode="rw",
        data_type="enum",
        specs={"0": "不设置", "1": "优", "2": "良", "3": "中", "4": "差"},
    )

    hcho_number = IamAirNumber(
        coordinator,
        device,
        prop=hcho,
        default_unit=None,
    )
    voc_select = IamAirSelect(coordinator, device, voc)

    assert hcho_number.native_min_value == 0
    assert hcho_number.native_max_value == 0.1
    assert hcho_number.native_step == 0.01
    assert voc_select.options == ["不设置", "良", "中", "差"]

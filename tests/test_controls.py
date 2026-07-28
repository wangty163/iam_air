"""Tests for the XDJ/Y control surface used by the IAM App."""

from unittest.mock import AsyncMock, MagicMock

from custom_components.iam_air.button import IamAirFilterResetButton
from custom_components.iam_air.fan import IamAirFan
from custom_components.iam_air.models import DeviceSnapshot, parse_device
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


async def test_fan_exposes_power_six_speeds_and_three_modes() -> None:
    """The primary fan exposes the same core controls as the App."""
    device, coordinator = make_device_and_coordinator()
    fan = IamAirFan(coordinator, device)

    assert fan.is_on
    assert fan.speed_count == 6
    assert fan.percentage == 50
    assert fan.preset_modes == ["自动", "手动", "睡眠"]
    assert fan.preset_mode == "手动"

    await fan.async_set_percentage(100)
    coordinator.async_set_properties.assert_awaited_once_with(
        "fake-device-id",
        {"WindSpeed": 5, "PowerSwitch": 1},
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

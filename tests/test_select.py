"""Tests for IAM Air select option presentation and control values."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.iam_air.models import DeviceSnapshot, IamAirDevice, TslProperty
from custom_components.iam_air.select import IamAirSelect


class FakeCoordinator:
    """Minimal coordinator surface used by select entities."""

    def __init__(self, device: IamAirDevice, properties: dict[str, Any]) -> None:
        self.last_update_success = True
        self.data = {
            device.iot_id: DeviceSnapshot(
                properties=properties,
                available=True,
                online=True,
            )
        }
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def async_set_properties(
        self,
        iot_id: str,
        properties: dict[str, Any],
    ) -> None:
        """Record one outgoing property update."""
        self.calls.append((iot_id, properties))


def make_device(model: str, prop: TslProperty) -> IamAirDevice:
    """Build one purifier exposing the supplied wind-speed property."""
    return IamAirDevice(
        iot_id="test-device",
        name="Test purifier",
        model=model,
        product_key="",
        device_name="",
        online=True,
        properties={prop.identifier: prop},
    )


@pytest.mark.asyncio
async def test_m8_pro_wind_speed_uses_numbered_app_options() -> None:
    """M8 Pro exposes the numbered labels used by the official App."""
    prop = TslProperty(
        identifier="WindSpeed",
        name="Wind speed",
        access_mode="rw",
        data_type="enum",
        specs={
            "0": "自动风",
            "1": "静音",
            "2": "低速",
            "3": "中速",
            "4": "高速",
            "5": "极速",
        },
    )
    device = make_device("KJ800F-M8 Pro", prop)
    coordinator = FakeCoordinator(
        device,
        {"WindSpeed": 3, "PowerSwitch": 1},
    )

    entity = IamAirSelect(coordinator, device, prop)

    assert entity.options == ["自动", "1档", "2档", "3档", "4档", "5档"]
    assert entity.current_option == "3档"

    await entity.async_select_option("5档")

    assert coordinator.calls == [("test-device", {"WindSpeed": 5})]


def test_other_models_keep_tsl_wind_speed_labels() -> None:
    """The M8-specific presentation does not alter other purifier models."""
    prop = TslProperty(
        identifier="WindSpeed",
        name="Wind speed",
        access_mode="rw",
        data_type="enum",
        specs={"0": "自动风", "1": "静音", "2": "高速"},
    )
    device = make_device("KJ500F-A1", prop)
    coordinator = FakeCoordinator(device, {"WindSpeed": 1})

    entity = IamAirSelect(coordinator, device, prop)

    assert entity.options == ["自动风", "静音", "高速"]
    assert entity.current_option == "静音"

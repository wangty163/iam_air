"""Shared IAM Air entity helpers."""

from __future__ import annotations

from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import IamAirCoordinator
from .models import IamAirDevice, TslProperty, value_as_bool

APP_PROPERTY_NAMES = {
    "childlockswitch": "童锁",
    "currenthumidity": "室内湿度",
    "currenttemperature": "室内温度",
    "disinfectswitch": "消毒",
    "hcho": "甲醛",
    "ionsswitch": "负离子",
    "pm25": "PM2.5",
    "pm25level": "PM2.5 等级",
    "powerswitch": "电源",
    "runtime_1": "累计运行时间",
    "screenswitch": "屏幕显示",
    "t_disinfectswitch": "自动运行 消毒",
    "t_ionsswitch": "自动运行 负离子",
    "t_off_hcho": "自动待机 甲醛",
    "t_off_pm25": "自动待机 PM2.5",
    "t_off_tvoclevel": "自动待机 VOC",
    "t_on_hcho": "自动运行 甲醛",
    "t_on_pm25": "自动运行 PM2.5",
    "t_on_tvoclevel": "自动运行 VOC",
    "timingoff": "定时关机",
    "timingon": "定时开机",
    "timingremain": "定时剩余时间",
    "trusteeship": "智能托管",
    "tvoclevel": "异味指数(VOC)",
    "windspeed": "风速",
    "workmode": "模式",
}


def app_property_name(device: IamAirDevice, prop: TslProperty) -> str:
    """Return the label rendered by the App for a TSL property."""
    identifier = prop.identifier.casefold()
    for prefix, suffix in (
        ("filterruntime_", "累计使用时间"),
        ("filterstatus_", "状态"),
    ):
        if not identifier.startswith(prefix):
            continue
        try:
            index = int(identifier.removeprefix(prefix)) - 1
            filter_name = device.filter_names[index]
        except (IndexError, ValueError):
            filter_name = None
        if filter_name:
            return f"{filter_name}{suffix}"
    return APP_PROPERTY_NAMES.get(identifier, prop.name)


def add_iam_entities(
    entry: Any,
    async_add_entities: AddEntitiesCallback,
    entities: list[IamAirEntity],
) -> None:
    """Register the active unique IDs before adding entities to HA."""
    entry.runtime_data.active_unique_ids.update(
        entity.unique_id for entity in entities if entity.unique_id is not None
    )
    async_add_entities(entities)


class IamAirEntity(CoordinatorEntity[IamAirCoordinator]):
    """Base entity bound to one discovered IAM air purifier."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: IamAirCoordinator,
        device: IamAirDevice,
        *,
        unique_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self.device = device
        self._attr_unique_id = f"{device.iot_id}_{unique_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.iot_id)},
            name=device.name,
            manufacturer="IAM",
            model=device.model,
        )

    @property
    def available(self) -> bool:
        """Return whether the coordinator has a live snapshot."""
        snapshot = (self.coordinator.data or {}).get(self.device.iot_id)
        return super().available and snapshot is not None and snapshot.available

    def property_value(self, identifier: str) -> Any:
        """Return one property from the latest snapshot."""
        snapshot = (self.coordinator.data or {}).get(self.device.iot_id)
        if snapshot is None:
            return None
        return snapshot.properties.get(identifier)

    def ensure_app_control_allowed(
        self,
        *,
        require_power: bool,
        allow_during_trusteeship: bool = False,
    ) -> None:
        """Apply the power and smart-trusteeship guards used by the App."""
        if (
            not allow_during_trusteeship
            and value_as_bool(self.property_value("Trusteeship"))
        ):
            raise HomeAssistantError("设备正在智能托管, 请先关闭智能托管")
        power = self.property_value("PowerSwitch")
        if require_power and power is not None and not value_as_bool(power):
            raise HomeAssistantError("设备未开机, 无法操作")

    def ensure_trusteeship_control_allowed(self, *, turn_on: bool) -> None:
        """Apply the App guards for enabling or disabling trusteeship."""
        if value_as_bool(self.property_value("ChildLockSwitch")):
            raise HomeAssistantError("童锁已开启, 无法操作智能托管")
        power = self.property_value("PowerSwitch")
        if turn_on and power is not None and not value_as_bool(power):
            raise HomeAssistantError("设备未开机, 无法开启智能托管")

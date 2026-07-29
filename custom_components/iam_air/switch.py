"""Switch platform for IAM air purifiers."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IamAirConfigEntry
from .const import POWER_PROPERTY_ALIASES
from .entity import IamAirEntity, add_iam_entities
from .models import IamAirDevice, TslProperty, value_as_bool

SWITCH_ALIASES = (
    POWER_PROPERTY_ALIASES,
    ("ChildLockSwitch", "childLockOnOff", "childLock", "ChildLock"),
    ("DisinfectSwitch", "disinfectSwitch", "disinfection", "Disinfection"),
    ("IonsSwitch", "ionsSwitch", "negativeIon"),
    ("ScreenSwitch", "screenSwitch"),
    ("Trusteeship", "TrustSwitch", "trustSwitch"),
    ("T_DisinfectSwitch",),
    ("T_IonsSwitch",),
)


async def async_setup_entry(
    _hass: Any,
    entry: IamAirConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up writable purifier switches."""
    coordinator = entry.runtime_data.coordinator
    entities: list[IamAirSwitch] = []
    for device in coordinator.devices.values():
        seen: set[str] = set()
        for aliases in SWITCH_ALIASES:
            prop = device.find_property(*aliases)
            if (
                prop is None
                or not prop.readable
                or not prop.writable
                or prop.identifier in seen
            ):
                continue
            seen.add(prop.identifier)
            entities.append(IamAirSwitch(coordinator, device, prop))
    add_iam_entities(entry, async_add_entities, entities)


class IamAirSwitch(IamAirEntity, SwitchEntity):
    """A writable boolean TSL property."""

    def __init__(
        self,
        coordinator: Any,
        device: IamAirDevice,
        prop: TslProperty,
    ) -> None:
        super().__init__(
            coordinator,
            device,
            unique_suffix=prop.identifier.lower(),
        )
        self._property = prop
        self._attr_name = prop.name

    @property
    def is_on(self) -> bool | None:
        """Return the current switch state."""
        if self._is_special_screen_switch:
            power = self.property_value("PowerSwitch")
            if power is not None and not value_as_bool(power):
                return False
            work_mode = self.property_value("WorkMode")
            if work_mode in (2, "2"):
                return False
            trusteeship = self.property_value("Trusteeship")
            if value_as_bool(trusteeship):
                panel_status = self.property_value("T_Panel_Status")
                if panel_status is not None:
                    return value_as_bool(panel_status)
        value = self.property_value(self._property.identifier)
        if value is None:
            return None
        return value_as_bool(value)

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Enable the property."""
        if self._is_special_screen_switch:
            await self._async_set_special_screen(True)
            return
        await self.coordinator.async_set_properties(
            self.device.iot_id,
            {self._property.identifier: self._property.coerce_value(1)},
        )

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Disable the property."""
        if self._is_special_screen_switch:
            await self._async_set_special_screen(False)
            return
        await self.coordinator.async_set_properties(
            self.device.iot_id,
            {self._property.identifier: self._property.coerce_value(0)},
        )

    @property
    def _is_special_screen_switch(self) -> bool:
        return (
            self._property.identifier.casefold() == "screenswitch"
            and self.device.uses_kx_type_5_screen_behavior
        )

    async def _async_set_special_screen(self, turn_on: bool) -> None:
        """Apply the same KX type-5 screen constraints as the Android App."""
        if not value_as_bool(self.property_value("PowerSwitch")):
            raise HomeAssistantError(
                "The purifier must be powered on before changing its screen"
            )
        if value_as_bool(self.property_value("Trusteeship")):
            raise HomeAssistantError(
                "Disable smart trusteeship before changing the screen"
            )
        work_mode = self.property_value("WorkMode")
        if turn_on and work_mode in (2, "2"):
            await self.coordinator.async_set_properties(
                self.device.iot_id,
                {"WorkMode": 0},
            )
        if not turn_on and work_mode in (2, "2"):
            return
        await self.coordinator.async_set_properties(
            self.device.iot_id,
            {
                self._property.identifier: self._property.coerce_value(
                    1 if turn_on else 0
                )
            },
        )

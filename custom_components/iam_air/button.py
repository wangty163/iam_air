"""Button platform for explicit IAM air-purifier maintenance actions."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IamAirConfigEntry
from .entity import IamAirEntity, add_iam_entities
from .models import IamAirDevice, TslProperty

FILTER_RESET_ALIASES = ("FilterReset", "filterReset")


async def async_setup_entry(
    _hass: Any,
    entry: IamAirConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the two filter reset actions shown by the App."""
    coordinator = entry.runtime_data.coordinator
    entities: list[IamAirFilterResetButton] = []
    for device in coordinator.devices.values():
        prop = device.find_property(*FILTER_RESET_ALIASES)
        if prop is None or not prop.writable:
            continue
        entities.extend(
            IamAirFilterResetButton(
                coordinator,
                device,
                prop=prop,
                raw_value=raw_value,
                label=_filter_reset_label(device, raw_value, label),
            )
            for raw_value, label in prop.enum_options.items()
        )
    add_iam_entities(entry, async_add_entities, entities)


class IamAirFilterResetButton(IamAirEntity, ButtonEntity):
    """Reset one filter's accumulated use time."""

    def __init__(
        self,
        coordinator: Any,
        device: IamAirDevice,
        *,
        prop: TslProperty,
        raw_value: str,
        label: str,
    ) -> None:
        super().__init__(
            coordinator,
            device,
            unique_suffix=f"{prop.identifier.lower()}_{raw_value}",
        )
        self._property = prop
        self._raw_value = raw_value
        self._attr_name = label

    async def async_press(self) -> None:
        """Run the filter reset command."""
        await self.coordinator.async_set_properties(
            self.device.iot_id,
            {
                self._property.identifier: self._property.coerce_value(
                    self._raw_value
                )
            },
        )


def _filter_reset_label(
    device: IamAirDevice,
    raw_value: str,
    fallback: str,
) -> str:
    """Use the App's filter title for its matching maintenance action."""
    try:
        filter_name = device.filter_names[int(raw_value) - 1]
    except (IndexError, ValueError):
        filter_name = None
    return f"重置{filter_name}滤芯寿命" if filter_name else fallback

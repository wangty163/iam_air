"""Tests for coordinator write/read reconciliation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.iam_air.const import DEFAULT_SCAN_INTERVAL_SECONDS
from custom_components.iam_air.coordinator import (
    IamAirCoordinator,
    _PendingProperty,
    _reconcile_pending_properties,
)
from custom_components.iam_air.models import DeviceSnapshot


def test_external_app_changes_poll_within_five_seconds() -> None:
    """External App commands should reach HA within five seconds."""
    assert DEFAULT_SCAN_INTERVAL_SECONDS == 5


def test_pending_write_masks_stale_cloud_read() -> None:
    """A stale poll cannot immediately undo a successful control command."""
    pending = {
        "PowerSwitch": _PendingProperty(value=0, expires_at=160.0),
    }

    reconciled = _reconcile_pending_properties(
        {"PowerSwitch": 1, "PM25": 12},
        pending,
        now=100.0,
    )

    assert reconciled == {"PowerSwitch": 0, "PM25": 12}
    assert "PowerSwitch" in pending


def test_pending_write_clears_when_cloud_confirms_it() -> None:
    """The optimistic value is released as soon as cloud read-back agrees."""
    pending = {
        "PowerSwitch": _PendingProperty(value=0, expires_at=160.0),
    }

    reconciled = _reconcile_pending_properties(
        {"PowerSwitch": 0},
        pending,
        now=101.0,
    )

    assert reconciled == {"PowerSwitch": 0}
    assert pending == {}


def test_expired_pending_write_accepts_cloud_state() -> None:
    """A failed device command cannot be hidden indefinitely."""
    pending = {
        "PowerSwitch": _PendingProperty(value=0, expires_at=160.0),
    }

    reconciled = _reconcile_pending_properties(
        {"PowerSwitch": 1},
        pending,
        now=161.0,
    )

    assert reconciled == {"PowerSwitch": 1}
    assert pending == {}


async def test_successful_write_is_published_before_refresh() -> None:
    """A control command updates HA before requesting cloud read-back."""
    coordinator = object.__new__(IamAirCoordinator)
    coordinator.client = MagicMock()
    coordinator.client.async_set_properties = AsyncMock()
    coordinator.devices = {
        "fake-device-id": SimpleNamespace(iot_paas_type=1),
    }
    coordinator._pending_properties = {}
    coordinator.data = {
        "fake-device-id": DeviceSnapshot(properties={"PowerSwitch": 1, "PM25": 12})
    }
    coordinator.async_set_updated_data = MagicMock()
    coordinator.async_request_refresh = AsyncMock()

    await coordinator.async_set_properties(
        "fake-device-id",
        {"PowerSwitch": 0},
    )

    coordinator.client.async_set_properties.assert_awaited_once_with(
        "fake-device-id",
        {"PowerSwitch": 0},
        iot_paas_type=1,
    )
    published = coordinator.async_set_updated_data.call_args.args[0]
    assert published["fake-device-id"].properties == {
        "PowerSwitch": 0,
        "PM25": 12,
    }
    coordinator.async_request_refresh.assert_awaited_once_with()


async def test_toggle_command_can_publish_a_different_target_state() -> None:
    """A same-value App command may optimistically expose its toggle result."""
    coordinator = object.__new__(IamAirCoordinator)
    coordinator.client = MagicMock()
    coordinator.client.async_set_properties = AsyncMock()
    coordinator.devices = {
        "fake-device-id": SimpleNamespace(iot_paas_type=1),
    }
    coordinator._pending_properties = {}
    coordinator.data = {
        "fake-device-id": DeviceSnapshot(properties={"ScreenSwitch": 1})
    }
    coordinator.async_set_updated_data = MagicMock()
    coordinator.async_request_refresh = AsyncMock()

    await coordinator.async_set_properties(
        "fake-device-id",
        {"ScreenSwitch": 1},
        optimistic_items={"ScreenSwitch": 0},
    )

    coordinator.client.async_set_properties.assert_awaited_once_with(
        "fake-device-id",
        {"ScreenSwitch": 1},
        iot_paas_type=1,
    )
    published = coordinator.async_set_updated_data.call_args.args[0]
    assert published["fake-device-id"].properties["ScreenSwitch"] == 0
    assert coordinator._pending_properties["fake-device-id"][
        "ScreenSwitch"
    ].value == 0

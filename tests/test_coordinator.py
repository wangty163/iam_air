"""Tests for coordinator write/read reconciliation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.iam_air.const import (
    DEFAULT_SCAN_INTERVAL_SECONDS,
    FOG_SCAN_INTERVAL_SECONDS,
    IOT_PAAS_TYPE_FOG,
)
from custom_components.iam_air.coordinator import (
    IamAirCoordinator,
    _PendingProperty,
    _reconcile_pending_properties,
)
from custom_components.iam_air.models import DeviceSnapshot
from custom_components.iam_air.mqtt import MqttPropertyPush, MqttPropertyValue


def test_scan_intervals_balance_push_and_fog_app_coexistence() -> None:
    """FOG polling is fast while Link Living push keeps a slower fallback."""
    assert DEFAULT_SCAN_INTERVAL_SECONDS == 30
    assert FOG_SCAN_INTERVAL_SECONDS == 5


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
    coordinator._pushed_properties = {}
    coordinator._push_connected = False
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
    coordinator._pushed_properties = {}
    coordinator._push_connected = False
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


def test_mqtt_push_updates_snapshot_immediately() -> None:
    """An App property event should be visible without waiting for REST."""
    coordinator = object.__new__(IamAirCoordinator)
    coordinator.devices = {
        "fake-device-id": SimpleNamespace(iot_paas_type=None)
    }
    coordinator._pending_properties = {
        "fake-device-id": {
            "T_Panel_Status": _PendingProperty(value=1, expires_at=160.0),
        }
    }
    coordinator._pushed_properties = {}
    coordinator._push_connected = True
    coordinator.data = {
        "fake-device-id": DeviceSnapshot(
            properties={"T_Panel_Status": 1, "PM25": 12}
        )
    }
    coordinator.async_set_updated_data = MagicMock()

    coordinator.async_apply_property_push(
        MqttPropertyPush(
            iot_id="fake-device-id",
            items={
                "T_Panel_Status": MqttPropertyValue(value=0, timestamp=200),
            },
        )
    )

    published = coordinator.async_set_updated_data.call_args.args[0]
    assert published["fake-device-id"].properties == {
        "T_Panel_Status": 0,
        "PM25": 12,
    }
    assert coordinator._pending_properties == {}


def test_older_mqtt_push_cannot_undo_newer_state() -> None:
    """Per-property timestamps follow the App's merge behavior."""
    coordinator = object.__new__(IamAirCoordinator)
    coordinator.devices = {
        "fake-device-id": SimpleNamespace(iot_paas_type=None)
    }
    coordinator._pending_properties = {}
    coordinator._pushed_properties = {}
    coordinator._push_connected = True
    coordinator.data = {
        "fake-device-id": DeviceSnapshot(properties={"T_Panel_Status": 1})
    }
    coordinator.async_set_updated_data = MagicMock()

    coordinator.async_apply_property_push(
        MqttPropertyPush(
            iot_id="fake-device-id",
            items={
                "T_Panel_Status": MqttPropertyValue(value=0, timestamp=200),
            },
        )
    )
    coordinator.async_apply_property_push(
        MqttPropertyPush(
            iot_id="fake-device-id",
            items={
                "T_Panel_Status": MqttPropertyValue(value=1, timestamp=199),
            },
        )
    )

    assert coordinator.async_set_updated_data.call_count == 1


def test_disconnect_releases_push_overrides() -> None:
    """REST becomes authoritative again while MQTT is disconnected."""
    coordinator = object.__new__(IamAirCoordinator)
    coordinator._push_connected = True
    coordinator._pushed_properties = {
        "fake-device-id": {
            "T_Panel_Status": SimpleNamespace(value=0, timestamp=200),
        }
    }

    coordinator.async_set_push_connected(False)

    assert coordinator._push_connected is False
    assert coordinator._pushed_properties == {}


async def test_fog_rest_snapshot_replaces_previous_push_fallback() -> None:
    """A missed FOG event heals on the next five-second REST snapshot."""
    coordinator = object.__new__(IamAirCoordinator)
    coordinator.client = MagicMock()
    coordinator.client.async_get_properties = AsyncMock(
        return_value={"ScreenSwitch": 1}
    )
    coordinator.devices = {
        "fake-device-id": SimpleNamespace(iot_paas_type=IOT_PAAS_TYPE_FOG)
    }
    coordinator._pending_properties = {}
    coordinator._pushed_properties = {
        "fake-device-id": {
            "ScreenSwitch": SimpleNamespace(value=0, timestamp=200),
        }
    }
    coordinator._push_connected = True
    coordinator.data = {
        "fake-device-id": DeviceSnapshot(properties={"ScreenSwitch": 0})
    }

    result = await coordinator._async_update_data()

    assert result["fake-device-id"].properties["ScreenSwitch"] == 1
    assert coordinator._pushed_properties == {}

"""Tests for device-level availability coordination."""

from __future__ import annotations

import logging
import time
from typing import Any

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.iam_air.cloud import (
    IamAirApiError,
    IamAirAuthError,
    IamAirConnectionError,
)
from custom_components.iam_air.const import CLOUD_CONNECTION_GRACE_SECONDS
from custom_components.iam_air.coordinator import IamAirCoordinator
from custom_components.iam_air.models import DeviceSnapshot, IamAirDevice
from custom_components.iam_air.mqtt import (
    MqttDeviceStatus,
    MqttPropertyPush,
    MqttPropertyValue,
)

DEVICE_ID = "fake-device-id"


class FakeCloudClient:
    """Return controlled property and availability responses."""

    def __init__(
        self,
        *,
        properties: dict[str, Any] | Exception,
        online_states: dict[str, bool] | Exception,
    ) -> None:
        self.properties = properties
        self.online_states = online_states
        self.status_calls = 0

    async def async_get_properties(
        self,
        _iot_id: str,
        *,
        iot_paas_type: int | None = None,
    ) -> dict[str, Any]:
        del iot_paas_type
        if isinstance(self.properties, Exception):
            raise self.properties
        return self.properties

    async def async_get_device_online_states(
        self,
        devices: dict[str, int | None],
    ) -> dict[str, bool]:
        self.status_calls += 1
        self.status_devices = devices
        if isinstance(self.online_states, Exception):
            raise self.online_states
        return self.online_states


def make_coordinator(
    client: FakeCloudClient,
    *,
    online: bool | None = True,
) -> IamAirCoordinator:
    """Build the update-only coordinator state without starting Home Assistant."""
    device = IamAirDevice(
        iot_id=DEVICE_ID,
        name="Test purifier",
        model="M8",
        product_key="",
        device_name="",
        online=online,
        iot_paas_type=1,
    )
    coordinator = IamAirCoordinator.__new__(IamAirCoordinator)
    coordinator.client = client
    coordinator.devices = {DEVICE_ID: device}
    coordinator._device_online = {DEVICE_ID: online} if online is not None else {}
    coordinator._next_device_status_refresh = 0.0
    coordinator._pending_properties = {}
    coordinator._pushed_properties = {}
    coordinator._property_connection_failures = {}
    coordinator._push_connected = False
    coordinator.data = {
        DEVICE_ID: DeviceSnapshot(properties={"PM25": 7}, online=online),
    }
    return coordinator


@pytest.mark.asyncio
async def test_offline_status_overrides_cached_properties() -> None:
    """A successful cached property response cannot hide device offline state."""
    client = FakeCloudClient(
        properties={"PM25": 3},
        online_states={DEVICE_ID: False},
    )

    snapshots = await make_coordinator(client)._async_update_data()

    assert snapshots[DEVICE_ID].properties == {"PM25": 3}
    assert snapshots[DEVICE_ID].available is False
    assert snapshots[DEVICE_ID].online is False
    assert client.status_devices == {DEVICE_ID: 1}
    assert client.status_calls == 1


@pytest.mark.asyncio
async def test_status_failure_keeps_previous_online_state() -> None:
    """A transient status query failure does not create a false offline event."""
    client = FakeCloudClient(
        properties={"PM25": 3},
        online_states=IamAirApiError("temporary status failure"),
    )

    snapshots = await make_coordinator(client)._async_update_data()

    assert snapshots[DEVICE_ID].available is True


@pytest.mark.asyncio
async def test_known_offline_property_failure_is_not_global_failure() -> None:
    """An offline purifier remains a usable connectivity result."""
    client = FakeCloudClient(
        properties=IamAirApiError("device offline"),
        online_states={DEVICE_ID: False},
    )

    snapshots = await make_coordinator(client)._async_update_data()

    assert snapshots[DEVICE_ID].available is False
    assert snapshots[DEVICE_ID].properties == {"PM25": 7}


@pytest.mark.asyncio
async def test_online_property_failure_remains_update_failure() -> None:
    """API failures for an online purifier are not hidden by connection grace."""
    client = FakeCloudClient(
        properties=IamAirApiError("cloud unavailable"),
        online_states={DEVICE_ID: True},
    )

    with pytest.raises(UpdateFailed):
        await make_coordinator(client)._async_update_data()


@pytest.mark.asyncio
async def test_transient_connection_failure_keeps_last_good_snapshot(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One transport failure does not make a previously healthy device flicker."""
    client = FakeCloudClient(
        properties=IamAirConnectionError("cloud unavailable"),
        online_states={DEVICE_ID: True},
    )
    coordinator = make_coordinator(client)

    snapshots = await coordinator._async_update_data()

    assert snapshots[DEVICE_ID] == DeviceSnapshot(
        properties={"PM25": 7},
        available=True,
        online=True,
    )
    assert DEVICE_ID in coordinator._property_connection_failures
    assert "retaining the last successful snapshot" in caplog.text

    await coordinator._async_update_data()

    assert caplog.text.count("retaining the last successful snapshot") == 1


@pytest.mark.asyncio
async def test_connection_failure_after_grace_is_update_failure() -> None:
    """A sustained transport outage still becomes an actionable failure."""
    client = FakeCloudClient(
        properties=IamAirConnectionError("cloud unavailable"),
        online_states={DEVICE_ID: True},
    )
    coordinator = make_coordinator(client)
    coordinator._property_connection_failures[DEVICE_ID] = (
        time.monotonic() - CLOUD_CONNECTION_GRACE_SECONDS
    )

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_connection_grace_does_not_invent_unknown_availability() -> None:
    """Unknown connectivity retains the snapshot's prior availability."""
    client = FakeCloudClient(
        properties=IamAirConnectionError("cloud unavailable"),
        online_states={},
    )
    coordinator = make_coordinator(client, online=None)
    coordinator.data = {
        DEVICE_ID: DeviceSnapshot(
            properties={"PM25": 7},
            available=False,
            online=None,
        )
    }

    snapshots = await coordinator._async_update_data()

    assert snapshots[DEVICE_ID].available is False
    assert snapshots[DEVICE_ID].online is None


@pytest.mark.asyncio
async def test_connection_recovery_clears_grace_state(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A successful read ends the outage episode and records one recovery."""
    caplog.set_level(logging.INFO)
    client = FakeCloudClient(
        properties=IamAirConnectionError("cloud unavailable"),
        online_states={DEVICE_ID: True},
    )
    coordinator = make_coordinator(client)
    await coordinator._async_update_data()

    client.properties = {"PM25": 4}
    snapshots = await coordinator._async_update_data()

    assert snapshots[DEVICE_ID].properties == {"PM25": 4}
    assert coordinator._property_connection_failures == {}
    assert "cloud property refresh recovered" in caplog.text


@pytest.mark.asyncio
async def test_first_refresh_connection_failure_is_not_masked() -> None:
    """Setup cannot report success without any previously verified snapshot."""
    client = FakeCloudClient(
        properties=IamAirConnectionError("cloud unavailable"),
        online_states={DEVICE_ID: True},
    )
    coordinator = make_coordinator(client)
    coordinator.data = None

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert coordinator._property_connection_failures == {}


@pytest.mark.asyncio
async def test_auth_failure_bypasses_connection_grace() -> None:
    """Rejected credentials continue to request reauthentication immediately."""
    client = FakeCloudClient(
        properties=IamAirAuthError("authentication rejected"),
        online_states={DEVICE_ID: True},
    )

    with pytest.raises(ConfigEntryAuthFailed):
        await make_coordinator(client)._async_update_data()


def test_explicit_fog_status_keeps_power_off_separate_from_offline() -> None:
    """Connectivity events never rewrite or infer the power property."""
    coordinator = make_coordinator(
        FakeCloudClient(properties={}, online_states={}),
    )
    coordinator.data = {
        DEVICE_ID: DeviceSnapshot(
            properties={"PowerSwitch": 0, "PM25": 7},
            available=True,
            online=True,
        )
    }
    coordinator._property_connection_failures[DEVICE_ID] = time.monotonic()
    coordinator.async_set_updated_data = lambda data: setattr(
        coordinator,
        "data",
        data,
    )

    coordinator.async_apply_device_status(
        MqttDeviceStatus(iot_id=DEVICE_ID, online=False)
    )
    assert coordinator.data[DEVICE_ID].online is False
    assert coordinator.data[DEVICE_ID].available is False
    assert coordinator.data[DEVICE_ID].properties["PowerSwitch"] == 0
    assert coordinator._property_connection_failures == {}

    coordinator.async_apply_device_status(
        MqttDeviceStatus(iot_id=DEVICE_ID, online=True)
    )
    assert coordinator.data[DEVICE_ID].online is True
    assert coordinator.data[DEVICE_ID].available is True
    assert coordinator.data[DEVICE_ID].properties["PowerSwitch"] == 0


def test_fog_property_push_does_not_infer_connectivity() -> None:
    """FOG connectivity comes only from status events or homepage state."""
    coordinator = make_coordinator(
        FakeCloudClient(properties={}, online_states={}),
        online=False,
    )
    coordinator.data = {
        DEVICE_ID: DeviceSnapshot(
            properties={"PowerSwitch": 0},
            available=False,
            online=False,
        )
    }
    coordinator.async_set_updated_data = lambda data: setattr(
        coordinator,
        "data",
        data,
    )

    coordinator.async_apply_property_push(
        MqttPropertyPush(
            iot_id=DEVICE_ID,
            items={"PM25": MqttPropertyValue(value=5, timestamp=1)},
        )
    )

    assert coordinator.data[DEVICE_ID].properties["PM25"] == 5
    assert coordinator.data[DEVICE_ID].online is False
    assert coordinator.data[DEVICE_ID].available is False

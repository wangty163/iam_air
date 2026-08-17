import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.iam_air.const import FOG_MQTT_RETRY_MAX_SECONDS
from custom_components.iam_air.mqtt import (
    IamAirFogMqttPushClient,
    fog_mqtt_retry_delay,
    parse_fog_status_push,
)


def test_fog_retry_delay_is_exponential_and_bounded() -> None:
    assert [fog_mqtt_retry_delay(count) for count in range(1, 7)] == [
        5,
        10,
        20,
        40,
        80,
        160,
    ]
    assert fog_mqtt_retry_delay(7) == FOG_MQTT_RETRY_MAX_SECONDS
    assert fog_mqtt_retry_delay(100) == FOG_MQTT_RETRY_MAX_SECONDS


def test_fog_retry_delay_treats_non_positive_count_as_first_failure() -> None:
    assert fog_mqtt_retry_delay(0) == 5
    assert fog_mqtt_retry_delay(-1) == 5


def test_rejected_fog_credentials_discard_client_and_schedule_cleanup() -> None:
    cleanup_coroutines = []
    loop = SimpleNamespace(call_soon_threadsafe=lambda callback, *args: callback(*args))

    def create_background_task(coroutine, _name):
        cleanup_coroutines.append(coroutine)
        return Mock(spec=asyncio.Task)

    hass = SimpleNamespace(
        loop=loop,
        async_create_background_task=create_background_task,
    )
    on_connection = Mock()
    push_client = IamAirFogMqttPushClient(
        hass,
        cloud=Mock(),
        on_properties=Mock(),
        on_status=Mock(),
        on_connection=on_connection,
    )
    mqtt_client = Mock()
    push_client._mqtt = mqtt_client
    push_client._running = True
    push_client._connected = True

    push_client._replace_rejected_client(mqtt_client, "Not authorized")

    assert push_client._mqtt is None
    assert push_client._connected is False
    assert push_client._credential_failures == 1
    assert push_client._next_credential_retry_at > 0
    on_connection.assert_called_once_with(False)
    assert len(cleanup_coroutines) == 1
    cleanup_coroutines[0].close()


def test_stale_rejected_client_cannot_replace_current_client() -> None:
    hass = SimpleNamespace(loop=Mock())
    push_client = IamAirFogMqttPushClient(
        hass,
        cloud=Mock(),
        on_properties=Mock(),
        on_status=Mock(),
        on_connection=Mock(),
    )
    current_client = Mock()
    push_client._mqtt = current_client

    push_client._replace_rejected_client(Mock(), "old callback")

    assert push_client._mqtt is current_client
    assert push_client._credential_failures == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("online", True),
        ("offline", False),
    ),
)
def test_parse_fog_status_push_accepts_only_explicit_states(
    value: str,
    expected: bool,
) -> None:
    payload = (
        '{"deviceId":"test-device","data":{"status":"'
        + value
        + '","ip":"192.0.2.1"}}'
    ).encode()

    status = parse_fog_status_push(payload)

    assert status is not None
    assert status.iot_id == "test-device"
    assert status.online is expected


@pytest.mark.parametrize(
    "payload",
    (
        b'{"deviceId":"test-device","data":{"status":"unknown"}}',
        b'{"deviceId":"test-device","data":{"status":"ONLINE"}}',
        b'{"deviceId":"","data":{"status":"online"}}',
        b'{"deviceId":"test-device","data":{}}',
        b"not-json",
    ),
)
def test_parse_fog_status_push_rejects_unknown_shapes(payload: bytes) -> None:
    assert parse_fog_status_push(payload) is None


def test_fog_topic_suffix_routes_status_and_properties_separately() -> None:
    loop = SimpleNamespace(call_soon_threadsafe=lambda callback, *args: callback(*args))
    hass = SimpleNamespace(loop=loop)
    on_properties = Mock()
    on_status = Mock()
    push_client = IamAirFogMqttPushClient(
        hass,
        cloud=Mock(),
        on_properties=on_properties,
        on_status=on_status,
        on_connection=Mock(),
    )

    push_client._on_message(
        Mock(),
        None,
        SimpleNamespace(
            topic="/account/device/status",
            payload=b'{"deviceId":"test-device","data":{"status":"offline"}}',
        ),
    )

    on_status.assert_called_once()
    on_properties.assert_not_called()

    push_client._on_message(
        Mock(),
        None,
        SimpleNamespace(
            topic="/account/device/devdata",
            payload=b'{"deviceId":"test-device","data":{"PowerSwitch":0}}',
        ),
    )

    on_properties.assert_called_once()
    assert on_properties.call_args.args[0].items["PowerSwitch"].value == 0
    on_status.assert_called_once()

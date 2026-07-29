"""Tests for the App-compatible MQTT property channel."""

from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.iam_air.models import MobileMqttCredentials
from custom_components.iam_air.mqtt import (
    _call_soon_threadsafe,
    _start_client_loop,
    build_account_bind_payload,
    build_mqtt_login,
    mobile_topic,
    mqtt_broker_host,
    parse_fog_property_push,
    parse_property_push,
)


def credentials() -> MobileMqttCredentials:
    return MobileMqttCredentials(
        product_key="fakeProduct",
        device_name="fakeDevice",
        device_secret="fakeSecret",
    )


def test_mqtt_thread_name_does_not_expose_client_identity() -> None:
    client = MagicMock()
    client._thread = SimpleNamespace(name="credential-derived-name")

    _start_client_loop(client, "iam-air-fog-mqtt")

    client.loop_start.assert_called_once_with()
    assert client._thread.name == "iam-air-fog-mqtt"


def test_late_callback_is_dropped_after_hass_loop_closes() -> None:
    hass = MagicMock()
    hass.loop.call_soon_threadsafe.side_effect = RuntimeError("closed")

    _call_soon_threadsafe(hass, MagicMock(), "value")


def test_build_mqtt_login_matches_alibaba_device_signature() -> None:
    """The mobile triple should use the SDK's HMAC-SHA1 login."""
    client_id, username, password = build_mqtt_login(credentials())
    base_client_id = "fakeDevice&fakeProduct"
    sign_text = (
        f"clientId{base_client_id}"
        "deviceNamefakeDevice"
        "productKeyfakeProduct"
    )
    expected = hmac.new(
        b"fakeSecret",
        sign_text.encode(),
        hashlib.sha1,
    ).hexdigest().upper()

    assert client_id == (
        "fakeDevice&fakeProduct|securemode=2,_v=0.8.0,"
        "lan=Android,os=Android,signmethod=hmacsha1,ext=1|"
    )
    assert username == base_client_id
    assert password == expected


def test_mobile_topic_and_broker_are_scoped_to_temporary_identity() -> None:
    assert mqtt_broker_host("fakeProduct") == (
        "fakeProduct.iot-as-mqtt.cn-shanghai.aliyuncs.com"
    )
    assert mobile_topic(credentials(), "down", "#") == (
        "/sys/fakeProduct/fakeDevice/app/down/#"
    )
    with pytest.raises(ValueError):
        mqtt_broker_host("fake.example.com")


def test_account_bind_payload_matches_app_envelope() -> None:
    payload = build_account_bind_payload(
        credentials(),
        "fake-iot-token",
        message_id="42",
        timestamp_ms=1000,
    )

    assert json.loads(payload) == {
        "id": "42",
        "system": {"version": "1.0", "time": "1000"},
        "request": {"clientId": "fakeDevice&fakeProduct"},
        "params": {"iotToken": "fake-iot-token"},
    }
    assert b"fakeSecret" not in payload


def test_parse_property_push_keeps_item_timestamps() -> None:
    push = parse_property_push(
        json.dumps(
            {
                "method": "thing.properties",
                "params": {
                    "iotId": "fake-iot-id",
                    "items": {
                        "T_Panel_Status": {"time": 1234, "value": 0},
                        "PM25": {"time": "1235", "value": 12},
                    },
                },
            }
        ).encode()
    )

    assert push is not None
    assert push.iot_id == "fake-iot-id"
    assert push.items["T_Panel_Status"].value == 0
    assert push.items["T_Panel_Status"].timestamp == 1234
    assert push.items["PM25"].timestamp == 1235


@pytest.mark.parametrize(
    "payload",
    (
        b"not-json",
        b"[]",
        b'{"params":{}}',
        b'{"params":{"iotId":"fake","items":{}}}',
    ),
)
def test_parse_property_push_rejects_incomplete_messages(payload: bytes) -> None:
    assert parse_property_push(payload) is None


def test_parse_fog_property_push_expands_full_snapshot() -> None:
    push = parse_fog_property_push(
        json.dumps(
            {
                "bizCode": "device-property",
                "deviceId": "fake-fog-device",
                "data": {
                    "ScreenSwitch": 1,
                    "T_Panel_Status": 1,
                    "PM25": 12,
                },
                "timestamp": "2345",
            }
        ).encode()
    )

    assert push is not None
    assert push.iot_id == "fake-fog-device"
    assert push.items["ScreenSwitch"].value == 1
    assert push.items["ScreenSwitch"].timestamp == 2345
    assert push.items["PM25"].value == 12


@pytest.mark.parametrize(
    "payload",
    (
        b"not-json",
        b"[]",
        b'{"deviceId":"fake"}',
        b'{"deviceId":"fake","data":{}}',
    ),
)
def test_parse_fog_property_push_rejects_incomplete_messages(
    payload: bytes,
) -> None:
    assert parse_fog_property_push(payload) is None

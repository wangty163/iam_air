"""Tests for cloud signing and safe response parsing."""

import base64
import hashlib
import hmac
import json
from unittest.mock import AsyncMock

import pytest

from custom_components.iam_air.cloud import (
    ACCEPT_JSON,
    CONTENT_TYPE_JSON,
    IamAirAuthError,
    IamCloudClient,
    build_gateway_request,
    parse_iam_login_response,
    parse_iot_session_response,
    validate_oa_host,
)
from custom_components.iam_air.const import IOT_PAAS_TYPE_FOG


def test_gateway_signature_is_deterministic_and_secret_is_not_transmitted() -> None:
    """The canonical request is signed without putting the secret on the wire."""
    app_secret = "not-a-real-secret"
    request = build_gateway_request(
        path="/thing/properties/get",
        params={"iotId": "fake-device-id"},
        app_key="test-app-key",
        app_secret=app_secret,
        api_version="1.0.4",
        iot_token="fake-iot-token",
        timestamp_ms="1234567890000",
        nonce="00000000-0000-0000-0000-000000000000",
        date="Tue, 28 Jul 2026 00:00:00 GMT",
    )

    body = json.loads(request.body)
    assert body["request"]["iotToken"] == "fake-iot-token"
    assert app_secret not in request.body.decode()
    assert app_secret not in json.dumps(request.headers)

    content_md5 = base64.b64encode(
        hashlib.md5(request.body, usedforsecurity=False).digest()
    ).decode()
    canonical_headers = "\n".join(
        (
            "x-ca-key:test-app-key",
            "x-ca-nonce:00000000-0000-0000-0000-000000000000",
            "x-ca-stage:RELEASE",
            "x-ca-timestamp:1234567890000",
            "x-ca-version:1",
        )
    )
    canonical = (
        f"POST\n{ACCEPT_JSON}\n{content_md5}\n{CONTENT_TYPE_JSON}\n"
        "Tue, 28 Jul 2026 00:00:00 GMT\n"
        f"{canonical_headers}\n/thing/properties/get"
    )
    expected = base64.b64encode(
        hmac.new(
            app_secret.encode(),
            canonical.encode(),
            hashlib.sha1,
        ).digest()
    ).decode()
    assert request.headers["X-Ca-Signature"] == expected


def test_parse_iam_login_response_keeps_only_session_fields() -> None:
    """IAM login parsing neither needs nor returns a password."""
    session = parse_iam_login_response(
        {
            "status": 1000,
            "result": {
                "userId": "fake-user",
                "userName": "fake-account",
                "token": "fake-token",
                "imSign": "fake-sign",
            },
        },
        "fallback-account",
    )

    assert session.user_id == "fake-user"
    assert "password" not in repr(session).lower()


def test_parse_iam_login_rejects_failure() -> None:
    """IAM login failures become authentication errors."""
    with pytest.raises(IamAirAuthError):
        parse_iam_login_response(
            {"status": 1001, "message": "Authentication failed"},
            "fake-account",
        )


def test_parse_iot_session() -> None:
    """IoT session expiry and refresh fields are retained in memory."""
    session = parse_iot_session_response(
        {
            "data": {
                "iotToken": "fake-iot-token",
                "refreshToken": "fake-refresh-token",
                "identityId": "fake-identity",
                "iotTokenExpire": 3600,
            }
        }
    )

    assert session.expires_in == 3600
    assert session.identity_id == "fake-identity"
    assert "fake-iot-token" not in repr(session)
    assert "fake-refresh-token" not in repr(session)
    assert "fake-identity" not in repr(session)


@pytest.mark.asyncio
async def test_get_device_online_states_uses_each_devices_app_route() -> None:
    """FOG homepage state cannot be overridden by its binding-list status."""
    client = IamCloudClient.__new__(IamCloudClient)

    async def list_app_devices() -> list[dict[str, object]]:
        return [
            {"iotId": "fog-online-off", "powerStatus": 1},
            {"iotId": "fog-online-on", "powerStatus": 2},
            {"iotId": "fog-offline", "powerStatus": 0},
            {"iotId": "fog-unknown", "powerStatus": 9},
            {"iotId": "other-fog", "powerStatus": 0},
        ]

    async def list_devices() -> list[dict[str, object]]:
        return [
            {"iotId": "fog-online-off", "status": 3},
            {"iotId": "fog-online-on", "status": 3},
            {"iotId": "fog-offline", "status": 3},
            {"iotId": "link-online", "status": 1},
            {"iotId": "link-offline", "status": "3"},
            {"iotId": "link-unknown", "status": 2},
            {"iotId": "other-link", "status": 1},
        ]

    client.async_list_app_devices = list_app_devices
    client.async_list_devices = list_devices

    assert await client.async_get_device_online_states(
        {
            "fog-online-off": IOT_PAAS_TYPE_FOG,
            "fog-online-on": IOT_PAAS_TYPE_FOG,
            "fog-offline": IOT_PAAS_TYPE_FOG,
            "fog-unknown": IOT_PAAS_TYPE_FOG,
            "link-online": 0,
            "link-offline": 0,
            "link-unknown": 0,
        }
    ) == {
        "fog-online-off": True,
        "fog-online-on": True,
        "fog-offline": False,
        "link-online": True,
        "link-offline": False,
    }


@pytest.mark.asyncio
async def test_discovery_uses_fog_homepage_state_instead_of_binding_state() -> None:
    """A FOG purifier that is online but off starts as online."""
    client = IamCloudClient.__new__(IamCloudClient)

    async def list_app_devices() -> list[dict[str, object]]:
        return [
            {
                "iotId": "fog-purifier",
                "iotPaasType": IOT_PAAS_TYPE_FOG,
                "powerStatus": 1,
                "productName": "Test purifier",
            }
        ]

    async def list_devices() -> list[dict[str, object]]:
        return [
            {
                "iotId": "fog-purifier",
                "status": 3,
                "productKey": "test-product",
                "deviceName": "test-device",
            }
        ]

    async def list_product_configs() -> list[dict[str, object]]:
        return []

    async def get_detail(_iot_id: str) -> dict[str, object]:
        return {"productCategory": "KX", "productType": "5"}

    async def get_tsl(_iot_id: str) -> dict[str, object]:
        return {
            "properties": [
                {
                    "identifier": "PowerSwitch",
                    "accessMode": "rw",
                    "dataType": {"type": "bool"},
                },
                {
                    "identifier": "PM25",
                    "accessMode": "r",
                    "dataType": {"type": "int"},
                },
            ]
        }

    client.async_list_app_devices = list_app_devices
    client.async_list_devices = list_devices
    client.async_list_app_product_configs = list_product_configs
    client.async_get_app_device_detail = get_detail
    client.async_get_tsl = get_tsl

    devices = await client.async_discover_air_devices()

    assert len(devices) == 1
    assert devices[0].online is True
    assert devices[0].iot_paas_type == IOT_PAAS_TYPE_FOG


@pytest.mark.parametrize(
    "host",
    (
        "living-account.cn-shanghai.aliyuncs.com",
        "https://api.link.aliyun.com",
    ),
)
def test_validate_oa_host_accepts_alibaba_https(host: str) -> None:
    """Only Alibaba HTTPS endpoints can be used for OA exchange."""
    assert validate_oa_host(host)


@pytest.mark.parametrize(
    "host",
    (
        "http://living-account.cn-shanghai.aliyuncs.com",
        "https://example.invalid",
        "file:///tmp/token",
    ),
)
def test_validate_oa_host_rejects_untrusted_values(host: str) -> None:
    """Server-provided endpoints cannot redirect requests to arbitrary hosts."""
    with pytest.raises(IamAirAuthError):
        validate_oa_host(host)


async def test_device_online_states_use_each_device_transport() -> None:
    """FOG and Link Living devices use their authoritative App routes."""
    client = object.__new__(IamCloudClient)
    client.async_list_app_devices = AsyncMock(
        return_value=[{"iotId": "fog", "powerStatus": 1}]
    )
    client.async_list_devices = AsyncMock(
        return_value=[{"iotId": "link", "status": 8}]
    )

    states = await client.async_get_device_online_states(
        {"fog": 1, "link": 0}
    )

    assert states == {"fog": True, "link": False}
    client.async_list_app_devices.assert_awaited_once_with()
    client.async_list_devices.assert_awaited_once_with()

"""Tests for cloud signing and safe response parsing."""

import asyncio
import base64
import hashlib
import hmac
import json
import time

import pytest

from custom_components.iam_air.cloud import (
    ACCEPT_JSON,
    CONTENT_TYPE_JSON,
    IamAirAuthError,
    IamCloudClient,
    build_gateway_request,
    parse_iam_homepage_response,
    parse_iam_login_response,
    parse_iot_session_response,
    validate_oa_host,
)
from custom_components.iam_air.models import IotSession


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


@pytest.mark.parametrize("status", (1000, "1000"))
def test_parse_iam_login_response_keeps_only_session_fields(
    status: int | str,
) -> None:
    """IAM login parsing neither needs nor returns a password."""
    session = parse_iam_login_response(
        {
            "status": status,
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
    assert session.iam_token == "fake-token"
    assert session.im_sign == "fake-sign"
    assert "password" not in repr(session).lower()
    assert "fake-user" not in repr(session)
    assert "fake-account" not in repr(session)
    assert "fake-token" not in repr(session)
    assert "fake-sign" not in repr(session)


def test_parse_iam_login_rejects_failure() -> None:
    """IAM login failures become authentication errors."""
    with pytest.raises(IamAirAuthError):
        parse_iam_login_response(
            {"status": 1001, "message": "Authentication failed"},
            "fake-account",
        )


def test_parse_iam_login_allows_missing_optional_im_sign() -> None:
    """Accounts without an IM signature still have a valid IAM web session."""
    session = parse_iam_login_response(
        {
            "status": 1000,
            "result": {
                "userId": "fake-user",
                "userName": "fake-account",
                "token": "fake-token",
            },
        },
        "fallback-account",
    )

    assert session.im_sign == ""


def test_parse_iam_homepage_devices() -> None:
    """The app homepage parser keeps only device objects."""
    devices = parse_iam_homepage_response(
        {
            "status": "1000",
            "result": [
                {"iotId": "fake-visible-device"},
                "invalid",
                None,
            ],
        }
    )

    assert devices == [{"iotId": "fake-visible-device"}]


@pytest.mark.asyncio
async def test_discovery_intersects_app_homepage_with_link_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale Link binding is not exposed when the IAM app omits its iotId."""
    client = IamCloudClient(
        None,  # type: ignore[arg-type]
        username="fake-account",
        password="fake-password",
        app_key="fake-app-key",
        app_secret="fake-app-secret",
    )
    tsl = {
        "properties": [
            {
                "identifier": "powerstate",
                "accessMode": "rw",
                "dataType": {"type": "bool"},
            },
            {
                "identifier": "mode",
                "accessMode": "rw",
                "dataType": {"type": "enum", "specs": {"0": "Auto"}},
            },
        ]
    }
    tsl_requests: list[str] = []

    async def fake_app_devices() -> list[dict[str, object]]:
        return [{"iotId": "fake-visible-device"}]

    async def fake_link_devices() -> list[dict[str, object]]:
        return [
            {
                "iotId": "fake-stale-device",
                "productName": "Stale",
            },
            {
                "iotId": "fake-visible-device",
                "productName": "Visible",
            },
        ]

    async def fake_get_tsl(iot_id: str) -> dict[str, object]:
        tsl_requests.append(iot_id)
        return tsl

    monkeypatch.setattr(client, "async_list_app_devices", fake_app_devices)
    monkeypatch.setattr(client, "async_list_devices", fake_link_devices)
    monkeypatch.setattr(client, "async_get_tsl", fake_get_tsl)

    devices = await client.async_discover_air_devices()

    assert [device.iot_id for device in devices] == ["fake-visible-device"]
    assert tsl_requests == ["fake-visible-device"]


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


@pytest.mark.asyncio
async def test_concurrent_stale_session_requests_refresh_only_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent polling shares one recovery when another login invalidates a token."""
    client = IamCloudClient(
        None,  # type: ignore[arg-type]
        username="fake-account",
        password="fake-password",
        app_key="fake-app-key",
        app_secret="fake-app-secret",
    )
    old_session = IotSession(
        iot_token="fake-old-token",
        refresh_token="fake-old-refresh",
        identity_id="old-identity",
        expires_in=3600,
        created_at=time.monotonic(),
    )
    new_session = IotSession(
        iot_token="fake-new-token",
        refresh_token="fake-new-refresh",
        identity_id="new-identity",
        expires_in=3600,
        created_at=time.monotonic(),
    )
    client._iot_session = old_session

    stale_calls = 0
    stale_ready = asyncio.Event()
    refresh_calls = 0

    async def fake_gateway_call(
        _path: str,
        _params: dict[str, object],
        *,
        api_version: str,
        iot_token: str | None,
        **_kwargs: object,
    ) -> dict[str, object]:
        nonlocal stale_calls
        assert api_version
        if iot_token == "fake-old-token":
            stale_calls += 1
            if stale_calls == 2:
                stale_ready.set()
            await stale_ready.wait()
            raise IamAirAuthError("session replaced")
        assert iot_token == "fake-new-token"
        return {"code": 200}

    async def fake_refresh() -> None:
        nonlocal refresh_calls
        refresh_calls += 1
        client._iot_session = new_session

    monkeypatch.setattr(client, "_async_gateway_call", fake_gateway_call)
    monkeypatch.setattr(client, "_async_refresh_iot_session", fake_refresh)

    results = await asyncio.gather(
        client._async_session_gateway_call(
            "/fake",
            {},
            api_version="1.0.0",
        ),
        client._async_session_gateway_call(
            "/fake",
            {},
            api_version="1.0.0",
        ),
    )

    assert results == [{"code": 200}, {"code": 200}]
    assert stale_calls == 2
    assert refresh_calls == 1

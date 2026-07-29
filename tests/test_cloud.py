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
    IamAirApiError,
    IamAirAuthError,
    IamCloudClient,
    build_gateway_request,
    parse_iam_homepage_response,
    parse_iam_login_response,
    parse_iot_paas_type,
    parse_iot_session_response,
    validate_oa_host,
)
from custom_components.iam_air.const import (
    API_VERSION_PROPERTIES_SET,
    IAM_FOG_CONTROL_PATH,
    IAM_FOG_PROPERTIES_PATH,
    IAM_FOG_PROPERTIES_VERSION,
    IOT_PAAS_TYPE_FOG,
    PATH_PROPERTIES_SET,
)
from custom_components.iam_air.models import IamAccountSession, IotSession


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
        return [
            {
                "iotId": "fake-visible-device",
                "iotPaasType": IOT_PAAS_TYPE_FOG,
                "productName": "App-visible purifier",
            }
        ]

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
    assert devices[0].name == "App-visible purifier"
    assert devices[0].iot_paas_type == IOT_PAAS_TYPE_FOG
    assert tsl_requests == ["fake-visible-device"]


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (1, 1),
        ("1", 1),
        (None, None),
        ("invalid", None),
    ),
)
def test_parse_iot_paas_type(value: object, expected: int | None) -> None:
    """Homepage route markers tolerate numeric strings and missing values."""
    assert parse_iot_paas_type(value) == expected


@pytest.mark.asyncio
async def test_fog_device_properties_use_iam_app_control_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FOG devices use the same IAM JSON command route as the Android App."""
    client = IamCloudClient(
        None,  # type: ignore[arg-type]
        username="fake-account",
        password="fake-password",
        app_key="fake-app-key",
        app_secret="fake-app-secret",
    )
    client._account_session = IamAccountSession(
        user_id="fake-user",
        username="fake-account",
        iam_token="fake-token",
        im_sign="fake-sign",
    )
    captured: dict[str, object] = {}

    async def fake_post_json(
        url: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        **_kwargs: object,
    ) -> dict[str, object]:
        captured.update(url=url, body=body, headers=headers)
        return {"status": 1000, "message": "success"}

    monkeypatch.setattr(client, "_async_post_json", fake_post_json)

    await client.async_set_properties(
        "fake-device-id",
        {"PowerSwitch": 0},
        iot_paas_type=IOT_PAAS_TYPE_FOG,
    )

    assert str(captured["url"]).endswith(IAM_FOG_CONTROL_PATH)
    assert json.loads(captured["body"]) == {
        "deviceId": "fake-device-id",
        "operCmd": {"PowerSwitch": 0},
    }
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["token"] == "fake-token"
    assert headers["userName"] == "fake-account"
    assert headers["signStr"] == "fake-sign"
    assert headers["Content-Type"] == CONTENT_TYPE_JSON
    assert "fake-app-secret" not in repr(captured)


@pytest.mark.asyncio
async def test_fog_device_snapshot_uses_iam_app_property_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FOG snapshots come from the IAM route instead of stale Link state."""
    client = IamCloudClient(
        None,  # type: ignore[arg-type]
        username="fake-account",
        password="fake-password",
        app_key="fake-app-key",
        app_secret="fake-app-secret",
    )
    client._account_session = IamAccountSession(
        user_id="fake-user",
        username="fake-account",
        iam_token="fake-token",
        im_sign="fake-sign",
    )
    captured: dict[str, object] = {}

    async def fake_post_json(
        url: str,
        *,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        **_kwargs: object,
    ) -> dict[str, object]:
        captured.update(url=url, data=data, headers=headers)
        return {
            "status": "1000",
            "result": {
                "PowerSwitch": 1,
                "WindSpeed": 3,
            },
        }

    monkeypatch.setattr(client, "_async_post_json", fake_post_json)

    properties = await client.async_get_properties(
        "fake-device-id",
        iot_paas_type=IOT_PAAS_TYPE_FOG,
    )

    assert properties == {"PowerSwitch": 1, "WindSpeed": 3}
    assert str(captured["url"]).endswith(IAM_FOG_PROPERTIES_PATH)
    assert captured["data"] == {
        "deviceId": "fake-device-id",
        "version": IAM_FOG_PROPERTIES_VERSION,
    }
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["token"] == "fake-token"
    assert "fake-app-secret" not in repr(captured)


@pytest.mark.asyncio
async def test_concurrent_fog_requests_recover_replaced_iam_session_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Status 1040 triggers one serialized IAM relogin and request retries."""
    client = IamCloudClient(
        None,  # type: ignore[arg-type]
        username="fake-account",
        password="fake-password",
        app_key="fake-app-key",
        app_secret="fake-app-secret",
    )
    old_account = IamAccountSession(
        user_id="fake-user",
        username="fake-account",
        iam_token="fake-old-token",
        im_sign="fake-old-sign",
    )
    new_account = IamAccountSession(
        user_id="fake-user",
        username="fake-account",
        iam_token="fake-new-token",
        im_sign="fake-new-sign",
    )
    client._account_session = old_account
    stale_calls = 0
    stale_ready = asyncio.Event()
    refresh_calls = 0

    async def fake_post_json(
        _url: str,
        *,
        headers: dict[str, str] | None = None,
        **_kwargs: object,
    ) -> dict[str, object]:
        nonlocal stale_calls
        assert headers is not None
        if headers["token"] == "fake-old-token":
            stale_calls += 1
            if stale_calls == 2:
                stale_ready.set()
            await stale_ready.wait()
            return {"status": 1040, "message": "session replaced"}
        assert headers["token"] == "fake-new-token"
        return {"status": 1000, "result": {"PowerSwitch": 1}}

    async def fake_iam_login() -> IamAccountSession:
        nonlocal refresh_calls
        refresh_calls += 1
        return new_account

    monkeypatch.setattr(client, "_async_post_json", fake_post_json)
    monkeypatch.setattr(client, "_async_iam_login", fake_iam_login)

    results = await asyncio.gather(
        client.async_get_properties(
            "fake-device-id",
            iot_paas_type=IOT_PAAS_TYPE_FOG,
        ),
        client.async_get_properties(
            "fake-device-id",
            iot_paas_type=IOT_PAAS_TYPE_FOG,
        ),
    )

    assert results == [{"PowerSwitch": 1}, {"PowerSwitch": 1}]
    assert stale_calls == 2
    assert refresh_calls == 1
    assert client.account_session is new_account


@pytest.mark.asyncio
async def test_fog_control_failure_is_reported_without_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FOG failures surface the server message without dumping private payloads."""
    client = IamCloudClient(
        None,  # type: ignore[arg-type]
        username="fake-account",
        password="fake-password",
        app_key="fake-app-key",
        app_secret="fake-app-secret",
    )
    client._account_session = IamAccountSession(
        user_id="fake-user",
        username="fake-account",
        iam_token="fake-token",
        im_sign="fake-sign",
    )

    async def fake_post_json(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "status": 1001,
            "message": "control rejected",
            "result": {"private": "not-for-errors"},
        }

    monkeypatch.setattr(client, "_async_post_json", fake_post_json)

    with pytest.raises(IamAirApiError, match=r"^control rejected$"):
        await client.async_set_properties(
            "fake-device-id",
            {"PowerSwitch": 0},
            iot_paas_type=IOT_PAAS_TYPE_FOG,
        )


@pytest.mark.asyncio
async def test_feiyan_device_properties_use_link_living_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-FOG devices retain the Link Living property-set path."""
    client = IamCloudClient(
        None,  # type: ignore[arg-type]
        username="fake-account",
        password="fake-password",
        app_key="fake-app-key",
        app_secret="fake-app-secret",
    )
    captured: dict[str, object] = {}

    async def fake_gateway_call(
        path: str,
        params: dict[str, object],
        *,
        api_version: str,
    ) -> dict[str, object]:
        captured.update(path=path, params=params, api_version=api_version)
        return {"code": 200}

    monkeypatch.setattr(client, "_async_session_gateway_call", fake_gateway_call)

    await client.async_set_properties(
        "fake-device-id",
        {"PowerSwitch": 1},
        iot_paas_type=0,
    )

    assert captured == {
        "path": PATH_PROPERTIES_SET,
        "params": {
            "iotId": "fake-device-id",
            "items": {"PowerSwitch": 1},
        },
        "api_version": API_VERSION_PROPERTIES_SET,
    }


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

"""Tests for cloud signing and safe response parsing."""

import base64
import hashlib
import hmac
import json

import pytest

from custom_components.iam_air.cloud import (
    ACCEPT_JSON,
    CONTENT_TYPE_JSON,
    IamAirAuthError,
    build_gateway_request,
    parse_iam_login_response,
    parse_iot_session_response,
    validate_oa_host,
)


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

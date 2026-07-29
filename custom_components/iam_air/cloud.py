"""Async clients for IAM and Alibaba Link Living cloud APIs."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from email.utils import formatdate
from typing import Any
from urllib.parse import urljoin, urlparse

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout

from .const import (
    API_VERSION_CREATE_SESSION,
    API_VERSION_DEVICE_LIST,
    API_VERSION_PROPERTIES_GET,
    API_VERSION_PROPERTIES_SET,
    API_VERSION_REFRESH_SESSION,
    API_VERSION_REGION,
    API_VERSION_TSL_GET,
    HTTP_TIMEOUT_SECONDS,
    IAM_API_BASE_URL,
    IAM_APP_VERSION,
    IAM_DEVICE_DETAIL_PATH,
    IAM_DEVICE_DETAIL_VERSION,
    IAM_FOG_CONTROL_PATH,
    IAM_FOG_PROPERTIES_PATH,
    IAM_FOG_PROPERTIES_VERSION,
    IAM_HOMEPAGE_PATH,
    IAM_HOMEPAGE_PROTOCOL_VERSION,
    IAM_PROTOCOL_VERSION,
    IAM_SESSION_REPLACED_STATUS,
    IOT_API_BASE_URL,
    IOT_PAAS_TYPE_FOG,
    OA_LOGIN_API_PATH,
    OA_REGION_API_PATH,
    PATH_CREATE_SESSION,
    PATH_DEVICE_LIST,
    PATH_PROPERTIES_GET,
    PATH_PROPERTIES_SET,
    PATH_REFRESH_SESSION,
    PATH_TSL_GET,
    SESSION_ERROR_CODES,
)
from .models import (
    IamAccountSession,
    IamAirDevice,
    IotSession,
    parse_device,
    select_app_device_metadata,
)

ACCEPT_JSON = "application/json; charset=UTF-8"
CONTENT_TYPE_JSON = "application/json; charset=UTF-8"
CONTENT_TYPE_FORM = "application/x-www-form-urlencoded; charset=UTF-8"


class IamAirError(Exception):
    """Base IAM Air error."""


class IamAirAuthError(IamAirError):
    """Authentication failed."""


class IamAirConnectionError(IamAirError):
    """The remote service could not be reached."""


class IamAirApiError(IamAirError):
    """The remote API returned an error."""


@dataclass(frozen=True, slots=True)
class GatewayRequest:
    """Signed Alibaba API Gateway request."""

    body: bytes
    headers: dict[str, str]


class IamCloudClient:
    """Client for the IAM account service and Alibaba Link Living."""

    def __init__(
        self,
        http: ClientSession,
        *,
        username: str,
        password: str,
        app_key: str,
        app_secret: str,
    ) -> None:
        self._http = http
        self._username = username.strip()
        self._password = password
        self._app_key = app_key.strip()
        self._app_secret = app_secret.strip()
        self._account_session: IamAccountSession | None = None
        self._iot_session: IotSession | None = None
        self._iam_session_refresh_lock = asyncio.Lock()
        self._session_refresh_lock = asyncio.Lock()

    @property
    def account_session(self) -> IamAccountSession | None:
        """Return the current IAM account session."""
        return self._account_session

    @property
    def iot_session(self) -> IotSession | None:
        """Return the current Alibaba IoT session."""
        return self._iot_session

    async def async_login(self) -> None:
        """Log in to IAM and exchange the account identity for an IoT session."""
        account = await self._async_iam_login()
        oa_host = await self._async_resolve_oa_host(account.user_id)
        oa_session_id = await self._async_oa_login(account.user_id, oa_host)
        self._account_session = account
        self._iot_session = await self._async_create_iot_session(oa_session_id)

    async def async_list_devices(self) -> list[dict[str, Any]]:
        """Return all devices bound to the current account."""
        result = await self._async_session_gateway_call(
            PATH_DEVICE_LIST,
            {"pageNo": 1, "pageSize": 100},
            api_version=API_VERSION_DEVICE_LIST,
        )
        data = result.get("data") or {}
        devices = data.get("data") if isinstance(data, dict) else data
        return [item for item in devices or [] if isinstance(item, dict)]

    async def async_list_app_devices(self) -> list[dict[str, Any]]:
        """Return the devices selected by the IAM app's homepage service."""
        account = self._account_session
        if account is None:
            raise IamAirAuthError("IAM account session is not initialized")
        response = await self._async_iam_session_post_json(
            IAM_HOMEPAGE_PATH,
            data={
                "userId": account.user_id,
                "version": IAM_HOMEPAGE_PROTOCOL_VERSION,
            },
        )
        return parse_iam_homepage_response(response)

    async def async_get_app_device_detail(self, iot_id: str) -> dict[str, Any]:
        """Return the App's authoritative display metadata for a device."""
        account = self._account_session
        if account is None:
            raise IamAirAuthError("IAM account session is not initialized")
        response = await self._async_iam_session_post_json(
            IAM_DEVICE_DETAIL_PATH,
            data={
                "iotId": iot_id,
                "userId": account.user_id,
                "version": IAM_DEVICE_DETAIL_VERSION,
            },
        )
        if response.get("status") not in (1000, "1000"):
            message = response.get("message") or "IAM device detail query failed"
            raise IamAirApiError(str(message))
        result = response.get("result")
        if not isinstance(result, dict):
            raise IamAirApiError("IAM device detail response is invalid")
        return result

    async def async_get_tsl(self, iot_id: str) -> Any:
        """Fetch a device TSL."""
        result = await self._async_session_gateway_call(
            PATH_TSL_GET,
            {"iotId": iot_id},
            api_version=API_VERSION_TSL_GET,
        )
        return result.get("data") or {}

    async def async_discover_air_devices(self) -> list[IamAirDevice]:
        """Discover app-visible devices whose TSL looks like an air purifier."""
        app_devices = {
            str(item["iotId"]): item
            for item in await self.async_list_app_devices()
            if item.get("iotId")
        }
        discovered: list[IamAirDevice] = []
        for raw_device in await self.async_list_devices():
            iot_id = str(raw_device.get("iotId") or "")
            if not iot_id or iot_id not in app_devices:
                continue
            app_device = app_devices[iot_id]
            try:
                detail = await self.async_get_app_device_detail(iot_id)
            except (IamAirApiError, IamAirConnectionError):
                detail = {}
            try:
                tsl = await self.async_get_tsl(iot_id)
            except IamAirApiError:
                continue
            display_name, model_name = select_app_device_metadata(
                app_device,
                detail,
            )
            device = parse_device(
                raw_device,
                tsl,
                display_name=display_name,
                model_name=model_name,
                iot_paas_type=parse_iot_paas_type(
                    app_device.get("iotPaasType")
                ),
            )
            if device.looks_like_air_purifier:
                discovered.append(device)
        return discovered

    async def async_get_properties(
        self,
        iot_id: str,
        *,
        iot_paas_type: int | None = None,
    ) -> dict[str, Any]:
        """Return a device's property snapshot."""
        if iot_paas_type == IOT_PAAS_TYPE_FOG:
            return await self._async_get_fog_properties(iot_id)
        result = await self._async_session_gateway_call(
            PATH_PROPERTIES_GET,
            {"iotId": iot_id},
            api_version=API_VERSION_PROPERTIES_GET,
        )
        data = result.get("data")
        if not isinstance(data, dict):
            return {}
        return {
            identifier: item["value"]
            for identifier, item in data.items()
            if isinstance(item, dict) and "value" in item
        }

    async def _async_get_fog_properties(self, iot_id: str) -> dict[str, Any]:
        """Read properties through the IAM App's FOG device route."""
        response = await self._async_iam_session_post_json(
            IAM_FOG_PROPERTIES_PATH,
            data={
                "deviceId": iot_id,
                "version": IAM_FOG_PROPERTIES_VERSION,
            },
        )
        if response.get("status") not in (1000, "1000"):
            message = response.get("message") or "IAM FOG property query failed"
            raise IamAirApiError(str(message))
        result = response.get("result")
        if not isinstance(result, dict):
            raise IamAirApiError("IAM FOG property response is invalid")
        return result

    async def async_set_properties(
        self,
        iot_id: str,
        items: dict[str, Any],
        *,
        iot_paas_type: int | None = None,
    ) -> None:
        """Set one or more writable device properties."""
        if iot_paas_type == IOT_PAAS_TYPE_FOG:
            await self._async_set_fog_properties(iot_id, items)
            return
        await self._async_session_gateway_call(
            PATH_PROPERTIES_SET,
            {"iotId": iot_id, "items": items},
            api_version=API_VERSION_PROPERTIES_SET,
        )

    async def _async_set_fog_properties(
        self,
        iot_id: str,
        items: dict[str, Any],
    ) -> None:
        """Set properties through the IAM App's FOG device route."""
        body = json.dumps(
            {"deviceId": iot_id, "operCmd": items},
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        response = await self._async_iam_session_post_json(
            IAM_FOG_CONTROL_PATH,
            body=body,
            content_type=CONTENT_TYPE_JSON,
        )
        if response.get("status") not in (1000, "1000"):
            message = response.get("message") or "IAM FOG control failed"
            raise IamAirApiError(str(message))

    @staticmethod
    def _iam_api_headers(account: IamAccountSession) -> dict[str, str]:
        """Return the IAM App headers without exposing them to logs."""
        return {
            "token": account.iam_token,
            "userName": account.username,
            "signStr": account.im_sign,
            "appVersion": IAM_APP_VERSION,
            "phTypeName": "Home Assistant",
            "phOSVersion": "Home Assistant",
            "osType": "2",
        }

    async def _async_iam_session_post_json(
        self,
        path: str,
        *,
        data: dict[str, str] | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        """Call an IAM session API and recover once after status 1040."""
        account = self._account_session
        if account is None:
            raise IamAirAuthError("IAM account session is not initialized")
        response = await self._async_iam_api_post_json(
            path,
            account=account,
            data=data,
            body=body,
            content_type=content_type,
        )
        if str(response.get("status")) != str(IAM_SESSION_REPLACED_STATUS):
            return response

        async with self._iam_session_refresh_lock:
            if self._account_session is account:
                self._account_session = await self._async_iam_login()
        refreshed = self._account_session
        if refreshed is None:
            raise IamAirAuthError("IAM account session refresh failed")
        return await self._async_iam_api_post_json(
            path,
            account=refreshed,
            data=data,
            body=body,
            content_type=content_type,
        )

    async def _async_iam_api_post_json(
        self,
        path: str,
        *,
        account: IamAccountSession,
        data: dict[str, str] | None,
        body: bytes | None,
        content_type: str | None,
    ) -> dict[str, Any]:
        """Send one IAM API request using an explicit account session."""
        headers = self._iam_api_headers(account)
        if content_type is not None:
            headers["Content-Type"] = content_type
        return await self._async_post_json(
            urljoin(IAM_API_BASE_URL, path),
            data=data,
            body=body,
            headers=headers,
        )

    async def _async_iam_login(self) -> IamAccountSession:
        response = await self._async_post_json(
            urljoin(IAM_API_BASE_URL, "user/login"),
            data={
                "userName": self._username,
                "password": self._password,
                "version": IAM_PROTOCOL_VERSION,
            },
            headers={
                "appVersion": IAM_APP_VERSION,
                "phTypeName": "Home Assistant",
                "phOSVersion": "Home Assistant",
                "osType": "2",
            },
        )
        return parse_iam_login_response(response, self._username)

    async def _async_resolve_oa_host(self, auth_code: str) -> str:
        result = await self._async_gateway_call(
            OA_REGION_API_PATH,
            {"type": "THIRD_AUTHCODE", "authCode": auth_code},
            api_version=API_VERSION_REGION,
            iot_token=None,
            base_url=IOT_API_BASE_URL,
        )
        data = result.get("data") or {}
        host = data.get("oaApiGatewayEndpoint") if isinstance(data, dict) else None
        if not host:
            raise IamAirAuthError("Account region discovery returned no OA endpoint")
        return validate_oa_host(str(host))

    async def _async_oa_login(self, auth_code: str, oa_host: str) -> str:
        oauth_request = {
            "oauthPlateform": 23,
            "accessToken": None,
            "openId": None,
            "oauthAppKey": self._app_key,
            "tokenType": None,
            "authCode": auth_code,
            "userData": None,
        }
        form_params = {
            "loginByOauthRequest": json.dumps(
                oauth_request, separators=(",", ":"), ensure_ascii=False
            )
        }
        body = urllib.parse.urlencode(form_params).encode()
        headers = self._build_form_gateway_headers(form_params)
        response = await self._async_post_json(
            f"https://{validate_oa_host(oa_host)}{OA_LOGIN_API_PATH}",
            body=body,
            headers=headers,
        )
        outer_data = response.get("data") or {}
        inner_data = outer_data.get("data") if isinstance(outer_data, dict) else {}
        login_result = (
            inner_data.get("loginSuccessResult")
            if isinstance(inner_data, dict)
            else None
        )
        session_id = login_result.get("sid") if isinstance(login_result, dict) else None
        if not session_id:
            raise IamAirAuthError("Alibaba account authorization failed")
        return str(session_id)

    async def _async_create_iot_session(self, oa_session_id: str) -> IotSession:
        result = await self._async_gateway_call(
            PATH_CREATE_SESSION,
            {
                "request": {
                    "authCode": oa_session_id,
                    "appKey": self._app_key,
                    "accountType": "OA_SESSION",
                }
            },
            api_version=API_VERSION_CREATE_SESSION,
            iot_token=None,
        )
        return parse_iot_session_response(result)

    async def _async_refresh_iot_session(self) -> None:
        current = self._iot_session
        if not current or not current.refresh_token or not current.identity_id:
            await self.async_login()
            return
        try:
            result = await self._async_gateway_call(
                PATH_REFRESH_SESSION,
                {
                    "refreshToken": current.refresh_token,
                    "identityId": current.identity_id,
                },
                api_version=API_VERSION_REFRESH_SESSION,
                iot_token=None,
            )
            self._iot_session = parse_iot_session_response(result)
        except IamAirError:
            await self.async_login()

    async def _async_ensure_iot_session(self) -> None:
        session = self._iot_session
        if session is not None and (
            time.monotonic() < session.created_at + session.expires_in - 60
        ):
            return
        async with self._session_refresh_lock:
            current = self._iot_session
            if current is None:
                await self.async_login()
            elif time.monotonic() >= current.created_at + current.expires_in - 60:
                await self._async_refresh_iot_session()

    async def _async_session_gateway_call(
        self,
        path: str,
        params: dict[str, Any],
        *,
        api_version: str,
    ) -> dict[str, Any]:
        """Call a session API and recover once when another login invalidates it."""
        await self._async_ensure_iot_session()
        session = self._iot_session
        try:
            return await self._async_gateway_call(
                path,
                params,
                api_version=api_version,
                iot_token=self._required_iot_token(),
            )
        except IamAirAuthError:
            async with self._session_refresh_lock:
                if self._iot_session is session:
                    await self._async_refresh_iot_session()
            return await self._async_gateway_call(
                path,
                params,
                api_version=api_version,
                iot_token=self._required_iot_token(),
            )

    def _required_iot_token(self) -> str:
        if self._iot_session is None:
            raise IamAirAuthError("IoT session is not initialized")
        return self._iot_session.iot_token

    async def _async_gateway_call(
        self,
        path: str,
        params: dict[str, Any],
        *,
        api_version: str,
        iot_token: str | None,
        base_url: str = IOT_API_BASE_URL,
    ) -> dict[str, Any]:
        request = build_gateway_request(
            path=path,
            params=params,
            app_key=self._app_key,
            app_secret=self._app_secret,
            api_version=api_version,
            iot_token=iot_token,
        )
        response = await self._async_post_json(
            f"{base_url.rstrip('/')}{path}",
            body=request.body,
            headers=request.headers,
        )
        code = response.get("code")
        if code != 200:
            message = response.get("localizedMsg") or response.get("message") or "error"
            error_type = (
                IamAirAuthError if code in SESSION_ERROR_CODES else IamAirApiError
            )
            raise error_type(f"Link Living API error {code}: {message}")
        return response

    def _build_form_gateway_headers(
        self, form_params: dict[str, str]
    ) -> dict[str, str]:
        timestamp_ms = str(int(time.time() * 1000))
        nonce = str(uuid.uuid4()).upper()
        date = formatdate(usegmt=True)
        sign_headers = {
            "x-ca-key": self._app_key,
            "x-ca-nonce": nonce,
            "x-ca-stage": "RELEASE",
            "x-ca-timestamp": timestamp_ms,
            "x-ca-version": "1",
        }
        canonical_headers = "\n".join(
            f"{key}:{sign_headers[key]}" for key in sorted(sign_headers)
        )
        query = "&".join(f"{key}={value}" for key, value in sorted(form_params.items()))
        canonical = (
            f"POST\n{ACCEPT_JSON}\n\n{CONTENT_TYPE_FORM}\n{date}\n"
            f"{canonical_headers}\n{OA_LOGIN_API_PATH}?{query}"
        )
        return build_gateway_headers(
            app_key=self._app_key,
            app_secret=self._app_secret,
            canonical=canonical,
            nonce=nonce,
            timestamp_ms=timestamp_ms,
            date=date,
            content_type=CONTENT_TYPE_FORM,
            content_md5=None,
            sign_headers=sign_headers,
        )

    async def _async_post_json(
        self,
        url: str,
        *,
        data: dict[str, str] | None = None,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            async with self._http.post(
                url,
                data=data if body is None else body,
                headers=headers,
                timeout=ClientTimeout(total=HTTP_TIMEOUT_SECONDS),
            ) as response:
                result = await read_json_response(response)
        except (TimeoutError, ClientError) as err:
            raise IamAirConnectionError("Unable to reach IAM cloud") from err
        if not isinstance(result, dict):
            raise IamAirApiError("Cloud response is not a JSON object")
        return result


async def read_json_response(response: ClientResponse) -> Any:
    """Decode JSON while keeping credentials and response bodies out of errors."""
    if response.status in (401, 403):
        raise IamAirAuthError("Cloud authentication was rejected")
    if response.status >= 400:
        raise IamAirApiError(f"Cloud HTTP error {response.status}")
    try:
        return await response.json(content_type=None)
    except (TypeError, ValueError) as err:
        raise IamAirApiError("Cloud returned invalid JSON") from err


def parse_iam_login_response(
    response: dict[str, Any], fallback_username: str
) -> IamAccountSession:
    """Parse an IAM login response without retaining or exposing the password."""
    if response.get("status") not in (1000, "1000"):
        raise IamAirAuthError(str(response.get("message") or "IAM login failed"))
    result = response.get("result")
    if not isinstance(result, dict) or not all(
        result.get(field) for field in ("userId", "token")
    ):
        raise IamAirAuthError("IAM login response did not contain session details")
    return IamAccountSession(
        user_id=str(result["userId"]),
        username=str(result.get("userName") or fallback_username),
        iam_token=str(result["token"]),
        im_sign=str(result.get("imSign") or ""),
    )


def parse_iam_homepage_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse the IAM app homepage device list."""
    if response.get("status") not in (1000, "1000"):
        raise IamAirApiError(str(response.get("message") or "IAM homepage failed"))
    result = response.get("result")
    if not isinstance(result, list):
        raise IamAirApiError("IAM homepage response did not contain a device list")
    return [item for item in result if isinstance(item, dict)]


def parse_iot_paas_type(value: Any) -> int | None:
    """Parse the App's device control route marker."""
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def parse_iot_session_response(response: dict[str, Any]) -> IotSession:
    """Parse an IoT session response."""
    data = response.get("data")
    if not isinstance(data, dict) or not data.get("iotToken"):
        raise IamAirAuthError("IoT session response did not contain a token")
    try:
        expires_in = max(120, int(data.get("iotTokenExpire") or 7200))
    except TypeError, ValueError:
        expires_in = 7200
    return IotSession(
        iot_token=str(data["iotToken"]),
        refresh_token=str(data.get("refreshToken") or ""),
        identity_id=str(data.get("identityId") or data.get("identity") or ""),
        expires_in=expires_in,
        created_at=time.monotonic(),
    )


def validate_oa_host(value: str) -> str:
    """Validate a server-provided OA host before making a request."""
    candidate = value if "://" in value else f"https://{value}"
    parsed = urlparse(candidate)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not hostname:
        raise IamAirAuthError("Invalid OA endpoint")
    if not (
        hostname == "aliyun.com"
        or hostname.endswith(".aliyun.com")
        or hostname == "aliyuncs.com"
        or hostname.endswith(".aliyuncs.com")
    ):
        raise IamAirAuthError("Untrusted OA endpoint")
    return hostname


def build_gateway_request(
    *,
    path: str,
    params: dict[str, Any],
    app_key: str,
    app_secret: str,
    api_version: str,
    iot_token: str | None,
    timestamp_ms: str | None = None,
    nonce: str | None = None,
    date: str | None = None,
) -> GatewayRequest:
    """Build a deterministic, signed Alibaba API Gateway request."""
    request_data: dict[str, Any] = {
        "language": "zh-CN",
        "appKey": app_key,
        "apiVer": api_version,
    }
    if iot_token:
        request_data["iotToken"] = iot_token
    body_data = {
        "id": (nonce or str(uuid.uuid4()).upper()),
        "version": "1.0.0",
        "params": params,
        "request": request_data,
    }
    body = json.dumps(body_data, separators=(",", ":"), ensure_ascii=False).encode()
    content_md5 = base64.b64encode(
        hashlib.md5(body, usedforsecurity=False).digest()
    ).decode()
    timestamp_ms = timestamp_ms or str(int(time.time() * 1000))
    nonce = nonce or str(uuid.uuid4()).upper()
    date = date or formatdate(usegmt=True)
    sign_headers = {
        "x-ca-key": app_key,
        "x-ca-nonce": nonce,
        "x-ca-stage": "RELEASE",
        "x-ca-timestamp": timestamp_ms,
        "x-ca-version": "1",
    }
    canonical_headers = "\n".join(
        f"{key}:{sign_headers[key]}" for key in sorted(sign_headers)
    )
    canonical = (
        f"POST\n{ACCEPT_JSON}\n{content_md5}\n{CONTENT_TYPE_JSON}\n{date}\n"
        f"{canonical_headers}\n{path}"
    )
    headers = build_gateway_headers(
        app_key=app_key,
        app_secret=app_secret,
        canonical=canonical,
        nonce=nonce,
        timestamp_ms=timestamp_ms,
        date=date,
        content_type=CONTENT_TYPE_JSON,
        content_md5=content_md5,
        sign_headers=sign_headers,
    )
    return GatewayRequest(body=body, headers=headers)


def build_gateway_headers(
    *,
    app_key: str,
    app_secret: str,
    canonical: str,
    nonce: str,
    timestamp_ms: str,
    date: str,
    content_type: str,
    content_md5: str | None,
    sign_headers: dict[str, str],
) -> dict[str, str]:
    """Build API Gateway headers without exposing the signing secret."""
    signature = base64.b64encode(
        hmac.new(app_secret.encode(), canonical.encode(), hashlib.sha1).digest()
    ).decode()
    headers = {
        "Accept": ACCEPT_JSON,
        "Content-Type": content_type,
        "Date": date,
        "X-Ca-Key": app_key,
        "X-Ca-Nonce": nonce,
        "X-Ca-Stage": "RELEASE",
        "X-Ca-Timestamp": timestamp_ms,
        "X-Ca-Version": "1",
        "X-Ca-Signature-Headers": ",".join(sorted(sign_headers)),
        "X-Ca-Signature-Method": "HmacSHA1",
        "X-Ca-Signature": signature,
    }
    if content_md5 is not None:
        headers["Content-MD5"] = content_md5
    return headers

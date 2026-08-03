"""App-compatible Link Living MQTT property push channel."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
from homeassistant.core import HomeAssistant

from .cloud import IamAirError, IamCloudClient
from .const import (
    FOG_MQTT_BROKER_HOST,
    FOG_MQTT_BROKER_PORT,
    FOG_MQTT_KEEPALIVE_SECONDS,
    FOG_MQTT_RETRY_MAX_SECONDS,
    FOG_MQTT_RETRY_SECONDS,
    MQTT_BROKER_PORT,
    MQTT_KEEPALIVE_SECONDS,
    MQTT_RETRY_SECONDS,
    MQTT_TOKEN_CHECK_SECONDS,
)
from .models import FogMqttCredentials, MobileMqttCredentials

_LOGGER = logging.getLogger(__name__)
_PRODUCT_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_APP_MQTT_SDK_VERSION = "0.8.0"


def fog_mqtt_retry_delay(failure_count: int) -> int:
    """Return a bounded exponential delay for fresh FOG credentials."""
    exponent = max(0, int(failure_count) - 1)
    return min(
        FOG_MQTT_RETRY_MAX_SECONDS,
        FOG_MQTT_RETRY_SECONDS * (2 ** min(exponent, 10)),
    )


def _call_soon_threadsafe(
    hass: HomeAssistant,
    callback: Callable[..., Any],
    *args: Any,
) -> None:
    """Drop late MQTT callbacks after Home Assistant has closed its loop."""
    try:
        hass.loop.call_soon_threadsafe(callback, *args)
    except RuntimeError:
        return


def _start_client_loop(client: mqtt.Client, thread_name: str) -> None:
    """Start Paho without leaving its credential-derived thread name visible."""
    client.loop_start()
    thread = getattr(client, "_thread", None)
    if thread is not None:
        thread.name = thread_name


@dataclass(frozen=True, slots=True)
class MqttPropertyValue:
    """One timestamped property value from the mobile channel."""

    value: Any
    timestamp: int


@dataclass(frozen=True, slots=True)
class MqttPropertyPush:
    """A timestamped device property update."""

    iot_id: str
    items: dict[str, MqttPropertyValue]


def mqtt_broker_host(product_key: str) -> str:
    """Return the Alibaba MQTT endpoint for a validated product key."""
    if not _PRODUCT_KEY_PATTERN.fullmatch(product_key):
        raise ValueError("Invalid mobile MQTT product key")
    return f"{product_key}.iot-as-mqtt.cn-shanghai.aliyuncs.com"


def build_mqtt_login(
    credentials: MobileMqttCredentials,
) -> tuple[str, str, str]:
    """Build the client ID, username and password used by the App SDK."""
    base_client_id = f"{credentials.device_name}&{credentials.product_key}"
    sign_values = {
        "clientId": base_client_id,
        "deviceName": credentials.device_name,
        "productKey": credentials.product_key,
    }
    sign_text = "".join(
        f"{key}{sign_values[key]}" for key in sorted(sign_values)
    )
    password = hmac.new(
        credentials.device_secret.encode(),
        sign_text.encode(),
        hashlib.sha1,
    ).hexdigest().upper()
    client_id = (
        f"{base_client_id}|securemode=2,_v={_APP_MQTT_SDK_VERSION},"
        "lan=Android,os=Android,signmethod=hmacsha1,ext=1|"
    )
    return client_id, base_client_id, password


def mobile_topic(
    credentials: MobileMqttCredentials,
    direction: str,
    path: str,
) -> str:
    """Build a mobile-channel topic."""
    return (
        f"/sys/{credentials.product_key}/{credentials.device_name}"
        f"/app/{direction}/{path.lstrip('/')}"
    )


def build_account_bind_payload(
    credentials: MobileMqttCredentials,
    iot_token: str,
    *,
    message_id: str,
    timestamp_ms: int,
) -> bytes:
    """Build the same account-bind envelope used by the App SDK."""
    payload = {
        "id": message_id,
        "system": {
            "version": "1.0",
            "time": str(timestamp_ms),
        },
        "request": {
            "clientId": f"{credentials.device_name}&{credentials.product_key}",
        },
        "params": {"iotToken": iot_token},
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def parse_property_push(payload: bytes) -> MqttPropertyPush | None:
    """Parse a `/thing/properties` downstream event."""
    try:
        message = json.loads(payload)
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(message, dict):
        return None
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    iot_id = str(params.get("iotId") or "")
    raw_items = params.get("items")
    if not iot_id or not isinstance(raw_items, dict):
        return None

    received_at = int(time.time() * 1000)
    items: dict[str, MqttPropertyValue] = {}
    for identifier, item in raw_items.items():
        if not isinstance(identifier, str) or not isinstance(item, dict):
            continue
        if "value" not in item:
            continue
        try:
            timestamp = int(item.get("time") or received_at)
        except (TypeError, ValueError):
            timestamp = received_at
        items[identifier] = MqttPropertyValue(
            value=item["value"],
            timestamp=timestamp,
        )
    if not items:
        return None
    return MqttPropertyPush(iot_id=iot_id, items=items)


def parse_fog_property_push(payload: bytes) -> MqttPropertyPush | None:
    """Parse the full property snapshot published by the FOG broker."""
    try:
        message = json.loads(payload)
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(message, dict):
        return None
    iot_id = str(message.get("deviceId") or "")
    data = message.get("data")
    if not iot_id or not isinstance(data, dict) or not data:
        return None
    received_at = int(time.time() * 1000)
    try:
        timestamp = int(message.get("timestamp") or received_at)
    except (TypeError, ValueError):
        timestamp = received_at
    items = {
        identifier: MqttPropertyValue(value=value, timestamp=timestamp)
        for identifier, value in data.items()
        if isinstance(identifier, str)
    }
    if not items:
        return None
    return MqttPropertyPush(iot_id=iot_id, items=items)


class IamAirMqttPushClient:
    """Maintain the App's account-bound MQTT property channel."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        cloud: IamCloudClient,
        on_properties: Callable[[MqttPropertyPush], None],
        on_connection: Callable[[bool], None],
    ) -> None:
        self._hass = hass
        self._cloud = cloud
        self._on_properties = on_properties
        self._on_connection = on_connection
        self._credentials: MobileMqttCredentials | None = None
        self._mqtt: mqtt.Client | None = None
        self._supervisor_task: asyncio.Task[None] | None = None
        self._running = False
        self._connected = False
        self._bound = False
        self._last_published_token: str | None = None
        self._bind_reply_topic = ""
        self._downstream_topic = ""

    async def async_start(self) -> None:
        """Start the push channel without making REST fallback depend on it."""
        if self._running:
            return
        self._running = True
        try:
            await self._async_initialize()
        except (IamAirError, ValueError) as err:
            _LOGGER.warning(
                "Unable to initialize IAM Air property push; "
                "REST fallback remains active: %s",
                err,
            )
        self._supervisor_task = self._hass.async_create_background_task(
            self._async_supervise(),
            "iam_air_mqtt_supervisor",
        )

    async def async_stop(self) -> None:
        """Stop the push channel and its reconnect supervisor."""
        self._running = False
        if self._supervisor_task is not None:
            self._supervisor_task.cancel()
            try:
                await self._supervisor_task
            except asyncio.CancelledError:
                pass
            self._supervisor_task = None
        client = self._mqtt
        self._mqtt = None
        self._connected = False
        self._bound = False
        self._dispatch_connection(False)
        if client is not None:
            await self._hass.async_add_executor_job(self._stop_client, client)

    async def _async_initialize(self) -> None:
        if self._mqtt is not None:
            return
        credentials = await self._cloud.async_get_mobile_mqtt_credentials()
        host = mqtt_broker_host(credentials.product_key)
        client = await self._hass.async_add_executor_job(
            self._build_client,
            credentials,
        )

        self._credentials = credentials
        self._bind_reply_topic = mobile_topic(
            credentials,
            "down",
            "account/bind_reply",
        )
        self._downstream_topic = mobile_topic(credentials, "down", "#")
        self._mqtt = client
        client.connect_async(
            host,
            port=MQTT_BROKER_PORT,
            keepalive=MQTT_KEEPALIVE_SECONDS,
        )
        _start_client_loop(client, "iam-air-link-mqtt")

    def _build_client(self, credentials: MobileMqttCredentials) -> mqtt.Client:
        """Create the TLS client outside Home Assistant's event loop."""
        client_id, username, password = build_mqtt_login(credentials)
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=True,
            protocol=mqtt.MQTTv311,
        )
        client.username_pw_set(username, password)
        tls_context = ssl.create_default_context()
        tls_context.load_verify_locations(
            cafile=Path(__file__).with_name("alink_root_ca.pem")
        )
        client.tls_set_context(tls_context)
        client.tls_insecure_set(False)
        client.reconnect_delay_set(min_delay=1, max_delay=MQTT_RETRY_SECONDS)
        client.on_connect = self._on_connect
        client.on_connect_fail = self._on_connect_fail
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        return client

    async def _async_supervise(self) -> None:
        while self._running:
            if self._mqtt is None:
                try:
                    await self._async_initialize()
                except (IamAirError, ValueError) as err:
                    _LOGGER.debug("IAM Air property push retry failed: %s", err)
                delay = MQTT_RETRY_SECONDS
            else:
                if self._connected:
                    self._publish_bind_if_needed()
                delay = MQTT_TOKEN_CHECK_SECONDS
            await asyncio.sleep(delay)

    @staticmethod
    def _stop_client(client: mqtt.Client) -> None:
        client.disconnect()
        client.loop_stop()

    def _on_connect(
        self,
        client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            self._schedule_log(
                logging.WARNING,
                "IAM Air property push connection was rejected: %s",
                reason_code,
            )
            return
        self._connected = True
        self._bound = False
        self._last_published_token = None
        self._dispatch_connection(True)
        self._schedule_log(logging.INFO, "IAM Air property push connected")
        client.subscribe(self._downstream_topic, qos=0)
        self._publish_bind_if_needed()

    def _on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _disconnect_flags: mqtt.DisconnectFlags,
        _reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        self._connected = False
        self._bound = False
        self._last_published_token = None
        self._dispatch_connection(False)
        if self._running:
            self._schedule_log(
                logging.INFO,
                "IAM Air property push disconnected; reconnecting",
            )

    def _on_connect_fail(
        self,
        _client: mqtt.Client,
        _userdata: Any,
    ) -> None:
        if self._running:
            self._schedule_log(
                logging.WARNING,
                "IAM Air property push connection attempt failed; retrying",
            )

    def _on_message(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
        try:
            if message.topic == self._bind_reply_topic:
                self._handle_bind_reply(message.payload)
                return
            if push := parse_property_push(message.payload):
                _call_soon_threadsafe(
                    self._hass,
                    self._on_properties,
                    push,
                )
        except Exception as err:
            self._schedule_log(
                logging.ERROR,
                "Unable to process IAM Air property push: %s",
                type(err).__name__,
            )

    def _handle_bind_reply(self, payload: bytes) -> None:
        try:
            response = json.loads(payload)
            code = int(response.get("code"))
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            code = -1
        if code != 200:
            self._bound = False
            self._last_published_token = None
            self._schedule_log(
                logging.WARNING,
                "IAM Air MQTT account binding was rejected",
            )
        elif not self._bound:
            self._bound = True
            self._schedule_log(
                logging.INFO,
                "IAM Air property push account binding succeeded",
            )

    def _publish_bind_if_needed(self) -> None:
        client = self._mqtt
        credentials = self._credentials
        session = self._cloud.iot_session
        if (
            not self._connected
            or client is None
            or credentials is None
            or session is None
            or session.iot_token == self._last_published_token
        ):
            return
        now = int(time.time() * 1000)
        payload = build_account_bind_payload(
            credentials,
            session.iot_token,
            message_id=str(now),
            timestamp_ms=now,
        )
        topic = mobile_topic(credentials, "up", "account/bind")
        result = client.publish(topic, payload=payload, qos=0, retain=False)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            self._last_published_token = session.iot_token

    def _dispatch_connection(self, connected: bool) -> None:
        _call_soon_threadsafe(
            self._hass,
            self._on_connection,
            connected,
        )

    def _schedule_log(
        self,
        level: int,
        message: str,
        *args: Any,
    ) -> None:
        _call_soon_threadsafe(
            self._hass,
            _LOGGER.log,
            level,
            message,
            *args,
        )


class IamAirFogMqttPushClient:
    """Maintain the IAM App's account-scoped FOG property channel."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        cloud: IamCloudClient,
        on_properties: Callable[[MqttPropertyPush], None],
        on_connection: Callable[[bool], None],
    ) -> None:
        self._hass = hass
        self._cloud = cloud
        self._on_properties = on_properties
        self._on_connection = on_connection
        self._mqtt: mqtt.Client | None = None
        self._supervisor_task: asyncio.Task[None] | None = None
        self._running = False
        self._connected = False
        self._credential_failures = 0
        self._next_credential_retry_at = 0.0

    async def async_start(self) -> None:
        """Start FOG push while leaving REST polling available as fallback."""
        if self._running:
            return
        self._running = True
        try:
            await self._async_initialize()
        except IamAirError as err:
            _LOGGER.warning(
                "Unable to initialize IAM Air FOG property push; "
                "REST fallback remains active: %s",
                err,
            )
        self._supervisor_task = self._hass.async_create_background_task(
            self._async_supervise(),
            "iam_air_fog_mqtt_supervisor",
        )

    async def async_stop(self) -> None:
        """Stop the FOG property channel and reconnect supervisor."""
        self._running = False
        if self._supervisor_task is not None:
            self._supervisor_task.cancel()
            try:
                await self._supervisor_task
            except asyncio.CancelledError:
                pass
            self._supervisor_task = None
        client = self._mqtt
        self._mqtt = None
        self._connected = False
        self._dispatch_connection(False)
        if client is not None:
            await self._hass.async_add_executor_job(self._stop_client, client)

    async def _async_initialize(self) -> None:
        if self._mqtt is not None:
            return
        credentials = await self._cloud.async_get_fog_mqtt_credentials()
        client = await self._hass.async_add_executor_job(
            self._build_client,
            credentials,
        )
        self._mqtt = client
        client.connect_async(
            FOG_MQTT_BROKER_HOST,
            port=FOG_MQTT_BROKER_PORT,
            keepalive=FOG_MQTT_KEEPALIVE_SECONDS,
        )
        _start_client_loop(client, "iam-air-fog-mqtt")

    def _build_client(self, credentials: FogMqttCredentials) -> mqtt.Client:
        """Create the FOG TLS client outside Home Assistant's event loop."""
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=credentials.client_id,
            clean_session=True,
            protocol=mqtt.MQTTv311,
        )
        client.username_pw_set(credentials.username, credentials.password)
        client.tls_set_context(ssl.create_default_context())
        client.tls_insecure_set(False)
        client.reconnect_delay_set(
            min_delay=1,
            max_delay=FOG_MQTT_RETRY_MAX_SECONDS,
        )
        client.user_data_set(credentials.topic)
        client.on_connect = self._on_connect
        client.on_connect_fail = self._on_connect_fail
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        return client

    async def _async_supervise(self) -> None:
        while self._running:
            if self._mqtt is None:
                delay = self._next_credential_retry_at - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(min(delay, FOG_MQTT_RETRY_SECONDS))
                    continue
                try:
                    await self._async_initialize()
                except IamAirError as err:
                    retry_delay = self._schedule_credential_retry()
                    _LOGGER.log(
                        logging.ERROR
                        if self._credential_failures >= 3
                        else logging.WARNING,
                        "IAM Air FOG property push credential refresh failed; "
                        "REST fallback remains active; retrying in %d seconds: %s",
                        retry_delay,
                        type(err).__name__,
                    )
            await asyncio.sleep(FOG_MQTT_RETRY_SECONDS)

    async def _async_stop_detached_client(self, client: mqtt.Client) -> None:
        await self._hass.async_add_executor_job(self._stop_client, client)

    def _schedule_credential_retry(self) -> int:
        self._credential_failures += 1
        delay = fog_mqtt_retry_delay(self._credential_failures)
        self._next_credential_retry_at = time.monotonic() + delay
        return delay

    def _replace_rejected_client(
        self,
        client: mqtt.Client,
        reason: str,
    ) -> None:
        """Discard rejected credentials on Home Assistant's event loop."""
        if self._mqtt is not client:
            return
        self._mqtt = None
        self._connected = False
        self._dispatch_connection(False)
        retry_delay = self._schedule_credential_retry()
        _LOGGER.log(
            logging.ERROR if self._credential_failures >= 3 else logging.WARNING,
            "IAM Air FOG property push credentials were rejected (%s); "
            "REST fallback remains active; refreshing credentials in %d seconds",
            reason[:80],
            retry_delay,
        )
        self._hass.async_create_background_task(
            self._async_stop_detached_client(client),
            "iam_air_fog_mqtt_rejected_client_cleanup",
        )

    @staticmethod
    def _stop_client(client: mqtt.Client) -> None:
        client.disconnect()
        client.loop_stop()

    def _on_connect(
        self,
        client: mqtt.Client,
        topic: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            _call_soon_threadsafe(
                self._hass,
                self._replace_rejected_client,
                client,
                str(reason_code),
            )
            return
        if not isinstance(topic, str) or not topic:
            self._schedule_log(
                logging.ERROR,
                "IAM Air FOG property push topic is invalid",
            )
            return
        self._connected = True
        self._credential_failures = 0
        self._next_credential_retry_at = 0.0
        self._dispatch_connection(True)
        client.subscribe(topic, qos=1)
        self._schedule_log(logging.INFO, "IAM Air FOG property push connected")

    def _on_disconnect(
        self,
        client: mqtt.Client,
        _userdata: Any,
        _disconnect_flags: mqtt.DisconnectFlags,
        _reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        self._connected = False
        self._dispatch_connection(False)
        if self._running and _reason_code.is_failure:
            _call_soon_threadsafe(
                self._hass,
                self._replace_rejected_client,
                client,
                str(_reason_code),
            )
        elif self._running:
            self._schedule_log(
                logging.INFO,
                "IAM Air FOG property push disconnected; reconnecting",
            )

    def _on_connect_fail(
        self,
        _client: mqtt.Client,
        _userdata: Any,
    ) -> None:
        if self._running:
            self._schedule_log(
                logging.WARNING,
                "IAM Air FOG property push connection attempt failed; retrying",
            )

    def _on_message(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
        try:
            if push := parse_fog_property_push(message.payload):
                _call_soon_threadsafe(
                    self._hass,
                    self._on_properties,
                    push,
                )
        except Exception as err:
            self._schedule_log(
                logging.ERROR,
                "Unable to process IAM Air FOG property push: %s",
                type(err).__name__,
            )

    def _dispatch_connection(self, connected: bool) -> None:
        _call_soon_threadsafe(
            self._hass,
            self._on_connection,
            connected,
        )

    def _schedule_log(
        self,
        level: int,
        message: str,
        *args: Any,
    ) -> None:
        _call_soon_threadsafe(
            self._hass,
            _LOGGER.log,
            level,
            message,
            *args,
        )

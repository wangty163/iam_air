"""Constants for the IAM Air integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "iam_air"
PLATFORMS = (
    Platform.BUTTON,
    Platform.FAN,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
)

CONF_APP_KEY = "app_key"
CONF_APP_SECRET = "app_secret"  # noqa: S105 - legacy configuration field name
CREDENTIALS_DIRECTORY = "iam_air"
CREDENTIALS_FILENAME = "credentials.json"

IAM_API_BASE_URL = "https://xapp.ixingoo.com/xapp/"
IAM_DEVICE_DETAIL_PATH = "devCustInfo/devInfo"
IAM_DEVICE_DETAIL_VERSION = "1.0.0"
IAM_HOMEPAGE_PATH = "index/homepage"
IAM_FOG_CONTROL_PATH = "devOperate/operCmd"
IAM_FOG_PROPERTIES_PATH = "devOperate/findDevAllProperties"
IAM_FOG_PROPERTIES_VERSION = "3.5.0"
IAM_SESSION_REPLACED_STATUS = 1040
IAM_PRODUCT_CONFIG_PATH = "product/listInfo"
IAM_PRODUCT_CONFIG_VERSION = "2.1.2"
IOT_API_BASE_URL = "https://api.link.aliyun.com"
OA_REGION_API_PATH = "/living/account/region/get"
OA_LOGIN_API_PATH = "/api/prd/loginbyoauth.json"

DEFAULT_SCAN_INTERVAL_SECONDS = 10
CONTROL_STATE_GRACE_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 15
IAM_PROTOCOL_VERSION = "1.0.0"
IAM_HOMEPAGE_PROTOCOL_VERSION = "3.1.0"
IAM_APP_VERSION = "3.4.3"
SESSION_ERROR_CODES = frozenset((401, 403, 460, 29003))

API_VERSION_CREATE_SESSION = "1.0.4"
API_VERSION_DEVICE_LIST = "1.0.8"
API_VERSION_PROPERTIES_GET = "1.0.4"
API_VERSION_PROPERTIES_SET = "1.0.2"
API_VERSION_REFRESH_SESSION = "1.0.4"
API_VERSION_REGION = "1.0.2"
API_VERSION_TSL_GET = "1.0.4"

PATH_CREATE_SESSION = "/account/createSessionByAuthCode"
PATH_DEVICE_LIST = "/uc/listBindingByAccount"
PATH_PROPERTIES_GET = "/thing/properties/get"
PATH_PROPERTIES_SET = "/thing/properties/set"
PATH_REFRESH_SESSION = "/account/checkOrRefreshSession"
PATH_TSL_GET = "/thing/tsl/get"

IOT_PAAS_TYPE_FOG = 1

POWER_PROPERTY_ALIASES = ("PowerSwitch", "powerstate", "power")
SPEED_PROPERTY_ALIASES = ("WindSpeed", "windspeed", "fanSpeed")
MODE_PROPERTY_ALIASES = ("WorkMode", "workMode", "mode")

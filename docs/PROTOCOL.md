# Protocol notes

This document records only reusable protocol shape. It intentionally excludes
credentials, account data, device identifiers, captured traffic and proprietary
application secrets.

## IAM account service

- Base URL: `https://xapp.ixingoo.com/xapp/`
- Login: `POST user/login`
- Form fields: `userName`, `password`, `version`
- Success status: `1000`
- The successful result contains `userId`, `userName`, `token` and `imSign`.

The integration uses only the account identity needed to establish the
Link Living session. It never logs the login response or request body.

## Link Living authorization

The 心够智家 Android application uses Alibaba Link Living's custom-account
flow. After IAM login, the account identity is passed through:

1. `/living/account/region/get`
2. OA `/api/prd/loginbyoauth.json`
3. `/account/createSessionByAuthCode`

All API Gateway calls use the documented `x-ca-*` HMAC-SHA1 signature scheme.
App credentials are runtime configuration and are never part of source control.

## Device APIs

| Path | API version | Purpose |
| --- | --- | --- |
| `/uc/listBindingByAccount` | `1.0.8` | Discover bound devices |
| `/thing/tsl/get` | `1.0.4` | Fetch the device TSL |
| `/thing/properties/get` | `1.0.4` | Read property snapshot |
| `/thing/properties/set` | `1.0.2` | Write properties |
| `/account/checkOrRefreshSession` | `1.0.4` | Refresh IoT session |

Availability is channel-specific and must not be inferred from a power
property or a cached property response.

For Link Living devices, the binding-list `status` field is the device-level
availability source. Its values are `0` (inactive), `1` (online), `3`
(offline), and `8` (disabled).

For FOG devices (`iotPaasType=1`), the IAM App uses two explicit sources:

- `index/homepage` exposes `powerStatus=0` for offline,
  `powerStatus=1` for online and powered off, and `powerStatus=2` for online
  and powered on.
- The account MQTT wildcard contains a `status` leaf topic. Its
  `data.status` is exactly `online` or `offline`.

The FOG `devdata` leaf topic carries property snapshots. Its `PowerSwitch`
value is only the purifier's power state: `0` is powered off and `1` is
powered on. It is never an availability signal. Unknown or malformed status
values do not change the previous connectivity state.

References:

- [Alibaba user service](https://help.aliyun.com/zh/document_detail/129778.html)
- [Get device TSL](https://help.aliyun.com/document_detail/177847.html)
- [Get properties](https://help.aliyun.com/zh/document_detail/177868.html)
- [Set properties](https://help.aliyun.com/zh/document_detail/177844.html)

## Known air-purifier property aliases

The integration still validates these against the live TSL before creating an
entity or writing a value:

- Power: `powerstate`
- Fan speed: `windspeed`
- Mode: `mode`
- Air data: `PM25`, `HCHO`, `tvoc`, `airQualityGrade`
- Environment: `CuTemperature`, `CurrentHumidity`
- Filter state: `filterStatusOne`, `filterStatusTwo`, `filterStatusThree`
- Controls: `childLockOnOff`, `uvSterilization`, `IonsSwitch`,
  `disinfection`, `TrustSwitch`

No write is attempted for a property unless the live TSL reports write access.

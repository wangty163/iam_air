# Protocol notes

This document records only reusable protocol shape. It intentionally excludes
credentials, account data, device identifiers, captured traffic and proprietary
application secrets.

## Local application credentials

Link Living client calls require the AppKey/AppSecret belonging to IAM's own
application project. A key created in an unrelated Alibaba project cannot access
the user's IAM-bound devices.

The integration reads those values from the fixed private file
`/config/iam_air/credentials.json`. On POSIX hosts it rejects files readable by
the group or other users. Values are kept in memory only and are not copied to
new config entries, logs or diagnostics. The credentials file must never be
committed to this repository.

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
App credentials come from the user's local owner-only file at runtime and are
never part of source control.

## Device APIs

| Path | API version | Purpose |
| --- | --- | --- |
| `/uc/listBindingByAccount` | `1.0.8` | Discover bound devices |
| `/thing/tsl/get` | `1.0.4` | Fetch the device TSL |
| `/thing/properties/get` | `1.0.4` | Read property snapshot |
| `/thing/properties/set` | `1.0.5` | Write properties |
| `/account/checkOrRefreshSession` | `1.0.4` | Refresh IoT session |

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

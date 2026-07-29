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

The integration uses the account identity to establish the Link Living session,
query the app homepage and control devices whose homepage `iotPaasType` selects
IAM's FOG route. It never logs the login response or request body.

### App-visible device list

The app homepage does not render `/uc/listBindingByAccount` directly. It calls
`POST index/homepage` with the IAM `userId`, uses the IAM login token headers,
and renders the returned `result` list. Link Living can retain additional
bindings that are absent from this homepage result.

Discovery therefore treats homepage `iotId` values as the visibility source,
retains each device's `iotPaasType`, and intersects those IDs with Link Living
bindings. This is an ID-based association, not a product-key or model-family
allowlist.

### App device detail metadata

The homepage title is not the complete device identity. For every app-visible
device, the Android detail screen calls `POST devCustInfo/devInfo` with
`iotId`, the current IAM `userId`, and `version=1.0.0`. Its result distinguishes:

- `productName`: the editable device note shown by the detail screen;
- `defaultProductName`: the unedited default product name;
- `productTypeName`: the more specific product type/model label.

When `productName` differs from `defaultProductName`, the integration preserves
it as the user-defined device name. Otherwise it displays `productTypeName`,
falling back through the remaining non-empty names if detail metadata is
unavailable. This prevents a generic default product name from obscuring the
specific device type while keeping user custom names intact.

## Link Living authorization

The 心够智家 Android application uses Alibaba Link Living's custom-account
flow. After IAM login, the account identity is passed through:

1. `/living/account/region/get`
2. OA `/api/prd/loginbyoauth.json`
3. `/account/createSessionByAuthCode`

All API Gateway calls use the documented `x-ca-*` HMAC-SHA1 signature scheme.
App credentials come from the user's local owner-only file at runtime and are
never part of source control.

### Same-account session replacement

Creating a second Link Living session for the same IAM account invalidates the
previous session. The next request made with the old session returns code
`29003` with a missing-identity error. The client classifies this as an
authentication/session error, serializes refresh across concurrent device polls,
refreshes or recreates the IoT session once, and retries the original request.
The IAM account API can independently return status `1040` after another App
login replaces its token. FOG reads and writes serialize an IAM account relogin
and retry once when that happens. These recoveries can replace the other
client's session in turn. Stable simultaneous App and Home Assistant use
therefore still requires a separate IAM identity with the device shared to it.

## Device APIs

| Path | API version | Purpose |
| --- | --- | --- |
| `IAM index/homepage` | `3.1.0` | List devices visible in the app |
| `IAM devCustInfo/devInfo` | `1.0.0` | Resolve device note, default name and product type |
| `IAM product/listInfo` | `2.1.2` | Resolve model-specific filter maximum runtimes |
| `/uc/listBindingByAccount` | `1.0.8` | Resolve app-visible IDs to controllable bindings |
| `/thing/tsl/get` | `1.0.4` | Fetch the device TSL |
| `/thing/properties/get` | `1.0.4` | Read property snapshot |
| `/thing/properties/set` | `1.0.2` | Write properties for Feiyan devices |
| `IAM devOperate/findDevAllProperties` | `3.5.0` | Read FOG properties |
| `IAM devOperate/operCmd` | n/a | Write properties for FOG devices |
| `/account/checkOrRefreshSession` | `1.0.4` | Refresh IoT session |

### Device control routing

IAM's App supports two cloud control paths. The homepage `iotPaasType` is the
source of truth:

- `0` (Feiyan): send `{iotId, items}` to `/thing/properties/set`.
- `1` (FOG): read with form fields `{deviceId, version=3.5.0}` from IAM
  `devOperate/findDevAllProperties`, and write JSON `{deviceId, operCmd}` to
  IAM `devOperate/operCmd`, using the current IAM account headers for both.

The Android App performs the same branch for both reads and writes. A FOG device
can still expose its TSL and a stale property snapshot through Link Living,
while Link Living property writes return an offline-device error. Consequently,
successful Link Living reads are not evidence that either the snapshot is
current or the Link Living write path is valid for that device.

References:

- [Alibaba user service](https://help.aliyun.com/zh/document_detail/129778.html)
- [Get device TSL](https://help.aliyun.com/document_detail/177847.html)
- [Get properties](https://help.aliyun.com/zh/document_detail/177868.html)
- [Set properties](https://help.aliyun.com/zh/document_detail/177844.html)

## Confirmed XDJ/Y control surface

Static inspection of the IAM Android 3.4.3 XDJ detail implementation and a
live, redacted TSL capability check agree on the following reusable property
surface. The integration still validates every item against the live TSL before
creating an entity or writing a value:

- Main controls: `PowerSwitch`, `WindSpeed`, `WorkMode`
- Direct switches: `ChildLockSwitch`, `ScreenSwitch`, `IonsSwitch`,
  `DisinfectSwitch`, `Trusteeship`
- Timers: `TimingOn`, `TimingOff`, `TimingRemain`
- Trusteeship settings: `T_ON_PM25`, `T_OFF_PM25`, `T_ON_HCHO`,
  `T_OFF_HCHO`, `T_ON_TVOCLevel`, `T_OFF_TVOCLevel`,
  `T_DisinfectSwitch`, `T_IonsSwitch`
- Air and environment data: `PM25`, `PM25Level`, `HCHO`, `HCHOLevel`,
  `TVOCLevel`, `CurrentTemperature`, `CurrentHumidity`
- Filter and runtime data: `FilterRunTime_1`, `FilterRunTime_2`,
  `FilterStatus_1`, `FilterStatus_2`, `Runtime_1`
- Explicit maintenance action: `FilterReset`

The TSL can also advertise provisioning, account, Wi-Fi diagnostic or
model-internal properties. Those are not App device controls and are
intentionally not exposed. In particular, forced unbinding is never surfaced
as an entity. No write is attempted unless the live TSL reports write access.

### KX type-5 screen behavior

The Android App treats the KX product type `5` screen as context-sensitive:

- sleep mode forces the screen state off; requesting the screen also leaves
  sleep mode;
- smart trusteeship blocks the ordinary screen control until trusteeship is
  disabled;
- `ScreenSwitch` is the requested setting, but the M8 Pro can reset it shortly
  after acknowledging a command. HA therefore renders the actual lit state
  from `T_Panel_Status` whenever that telemetry is available. A powered-off or
  sleep-mode device is always rendered as screen off.

The Home Assistant switch mirrors those rules instead of presenting a
successful `ScreenSwitch` write as a lit panel when the panel telemetry or
another mode says otherwise.

### Filter lifetime percentage

`FilterStatus_1` and `FilterStatus_2` are replacement-status enums, not
remaining-life percentages. The App fetches `filterMaxRuntime` and
`filter2MaxRuntime` for the exact `productCategory` plus `productType` from
`product/listInfo`, then calculates each displayed percentage as:

`round((maximum runtime - FilterRunTime_n) / maximum runtime * 100)`

The integration uses the same model-specific limits and clamps the result to
0-100%. It does not substitute the generic TSL numeric maximum, because that
can differ from the App's configured lifetime for a particular filter.

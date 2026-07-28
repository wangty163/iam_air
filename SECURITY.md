# Security policy

## Reporting a vulnerability

Open a GitHub security advisory for vulnerabilities. Do not include secrets,
real account identifiers, device IDs, tokens, complete API responses, APK files,
HAR files, packet captures or unredacted Home Assistant diagnostics in a public
Issue.

## Credential handling

- This repository must never contain a real AppKey, AppSecret, password or token.
- The user supplies an official APK only on their own Home Assistant host; the
  repository does not download, bundle or redistribute it.
- AppKey/AppSecret values are extracted from the local APK into memory and are
  never written to the config entry, logs or diagnostics.
- The APK parser validates the expected DEX class/field shape, but does not
  cryptographically authenticate the APK publisher. Obtain the APK only from a
  trusted official channel.
- IAM account credentials are collected through Home Assistant's config flow.
- Cloud errors are reduced to status codes and safe messages.
- Request and response bodies are not logged.
- Server-provided OA endpoints are restricted to HTTPS Alibaba domains.

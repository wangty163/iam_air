# Security policy

## Reporting a vulnerability

Open a GitHub security advisory for vulnerabilities. Do not include secrets,
real account identifiers, device IDs, tokens, complete API responses, APK files,
HAR files, packet captures or unredacted Home Assistant diagnostics in a public
Issue.

## Credential handling

- This repository must never contain a real AppKey, AppSecret, password or token.
- Runtime credentials are collected through Home Assistant's config flow.
- Cloud errors are reduced to status codes and safe messages.
- Request and response bodies are not logged.
- Server-provided OA endpoints are restricted to HTTPS Alibaba domains.

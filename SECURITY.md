# Security policy

## Reporting a vulnerability

Open a GitHub security advisory for vulnerabilities. Do not include secrets,
real account identifiers, device IDs, tokens, complete API responses, APK files,
HAR files, packet captures or unredacted Home Assistant diagnostics in a public
Issue.

## Credential handling

- This repository must never contain a real AppKey, AppSecret, password or token.
- AppKey/AppSecret values live only in the user's owner-readable
  `/config/iam_air/credentials.json`; the repository does not download, bundle
  or redistribute them.
- The credential file must have mode `0600` on POSIX hosts. Values are loaded
  into memory and are never copied to new config entries, logs or diagnostics.
- IAM account credentials are collected through Home Assistant's config flow.
- Cloud errors are reduced to status codes and safe messages.
- Request and response bodies are not logged.
- Server-provided OA endpoints are restricted to HTTPS Alibaba domains.

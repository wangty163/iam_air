#!/usr/bin/env python3
"""Fail when public-repository files contain likely credentials or captures."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()

FORBIDDEN_FILENAMES = {
    ".env",
    "secrets.yaml",
    "auth",
}
FORBIDDEN_SUFFIXES = {
    ".aab",
    ".apk",
    ".apks",
    ".db",
    ".dex",
    ".har",
    ".pcap",
    ".pcapng",
    ".trace",
    ".xapk",
}
TEXT_SUFFIXES = {
    ".json",
    ".md",
    ".py",
    ".toml",
    ".yaml",
    ".yml",
}

PATTERNS = {
    "private key": re.compile(
        "-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
    "GitHub token": re.compile(r"\bgh[opsu]_[A-Za-z0-9]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "hardcoded sensitive value": re.compile(
        r"""(?ix)
        \b(?:app_?secret|iot_?token|refresh_?token|password)\b
        \s*[:=]\s*["']
        (?!
            example|fake|test|not-a-real|your-|<|\$|\{
        )
        [A-Za-z0-9+/=_-]{8,}
        ["']
        """
    ),
    "hardcoded AppKey": re.compile(
        r"""(?ix)
        \bapp_?key\b\s*[:=]\s*["']
        (?!example|fake|test|your-|<|\$|\{)
        [A-Za-z0-9_-]{8,}
        ["']
        """
    ),
}


def iter_files() -> list[Path]:
    """Return repository files while excluding local tooling state."""
    excluded_parts = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file() and not any(part in excluded_parts for part in path.parts)
    ]


def main() -> int:
    """Scan filenames and text content."""
    findings: list[str] = []
    for path in iter_files():
        relative = path.relative_to(ROOT)
        if path.name in FORBIDDEN_FILENAMES or path.suffix in FORBIDDEN_SUFFIXES:
            findings.append(f"{relative}: forbidden file type")
            continue
        if path == SELF or path.suffix not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8")
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{relative}: possible {label}")

    if findings:
        print("Sensitive information scan failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("Sensitive information scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

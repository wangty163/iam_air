"""Load Link Living application credentials from a private local file."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_CREDENTIALS_FILE_BYTES = 16 * 1024


class IamAirCredentialsError(Exception):
    """The local application credentials file is unavailable or invalid."""


@dataclass(frozen=True, slots=True)
class IamAppCredentials:
    """Link Living application credentials kept out of object representations."""

    app_key: str = field(repr=False)
    app_secret: str = field(repr=False)


def load_app_credentials(path: str | Path) -> IamAppCredentials:
    """Load AppKey/AppSecret from a small owner-only JSON file."""
    credentials_path = Path(path)
    try:
        file_stat = credentials_path.stat()
    except OSError as err:
        raise IamAirCredentialsError("IAM credentials file is not readable") from err

    if (
        not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_size <= 0
        or file_stat.st_size > MAX_CREDENTIALS_FILE_BYTES
    ):
        raise IamAirCredentialsError("IAM credentials file has an invalid size")
    if os.name == "posix" and file_stat.st_mode & 0o077:
        raise IamAirCredentialsError(
            "IAM credentials file must be readable only by its owner"
        )

    try:
        data: Any = json.loads(credentials_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as err:
        raise IamAirCredentialsError("IAM credentials file is invalid JSON") from err

    if not isinstance(data, dict):
        raise IamAirCredentialsError("IAM credentials file must contain an object")
    app_key = data.get("app_key")
    app_secret = data.get("app_secret")
    if not isinstance(app_key, str) or not isinstance(app_secret, str):
        raise IamAirCredentialsError("IAM application credentials are missing")

    app_key = app_key.strip()
    app_secret = app_secret.strip()
    if not 1 <= len(app_key) <= 128 or not 8 <= len(app_secret) <= 256:
        raise IamAirCredentialsError("IAM application credentials are invalid")
    return IamAppCredentials(app_key=app_key, app_secret=app_secret)

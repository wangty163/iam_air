"""Tests for private local IAM application credentials."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.iam_air.credentials import (
    IamAirCredentialsError,
    load_app_credentials,
)


def _write_credentials(path: Path, data: object, mode: int = 0o600) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")
    path.chmod(mode)


def test_load_credentials_without_exposing_them(tmp_path: Path) -> None:
    """Valid owner-only credentials stay out of object representations."""
    path = tmp_path / "credentials.json"
    _write_credentials(
        path,
        {
            "app_key": "fake-app-key",
            "app_secret": "fake-app-secret",
        },
    )

    credentials = load_app_credentials(path)

    assert credentials.app_key == "fake-app-key"
    assert credentials.app_secret == "fake-app-secret"
    assert "fake-app-key" not in repr(credentials)
    assert "fake-app-secret" not in repr(credentials)


def test_reject_world_readable_credentials(tmp_path: Path) -> None:
    """Application secrets cannot be loaded from a broadly readable file."""
    path = tmp_path / "credentials.json"
    _write_credentials(
        path,
        {
            "app_key": "fake-app-key",
            "app_secret": "fake-app-secret",
        },
        mode=0o644,
    )

    with pytest.raises(IamAirCredentialsError):
        load_app_credentials(path)


@pytest.mark.parametrize(
    "data",
    (
        [],
        {},
        {"app_key": "fake-app-key"},
        {"app_key": "fake-app-key", "app_secret": "short"},
    ),
)
def test_reject_invalid_credentials(tmp_path: Path, data: object) -> None:
    """Malformed or incomplete credential files fail closed."""
    path = tmp_path / "credentials.json"
    _write_credentials(path, data)

    with pytest.raises(IamAirCredentialsError):
        load_app_credentials(path)

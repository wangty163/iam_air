"""Tests for IAM Air integration setup helpers."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.iam_air import (
    async_remove_stale_devices,
    async_remove_stale_entities,
)
from custom_components.iam_air.const import DOMAIN


def test_remove_stale_devices_uses_app_visible_iot_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only IAM devices missing from the app-visible ID set are removed."""
    entries = [
        SimpleNamespace(
            id="active-registry-device",
            identifiers={(DOMAIN, "fake-active-iot-id")},
            config_entries={"fake-entry"},
        ),
        SimpleNamespace(
            id="stale-registry-device",
            identifiers={(DOMAIN, "fake-stale-iot-id")},
            config_entries={"fake-entry"},
        ),
        SimpleNamespace(
            id="unrelated-registry-device",
            identifiers={("other_domain", "fake-stale-iot-id")},
            config_entries={"fake-entry"},
        ),
        SimpleNamespace(
            id="other-entry-device",
            identifiers={(DOMAIN, "fake-stale-iot-id")},
            config_entries={"other-entry"},
        ),
    ]
    registry = SimpleNamespace(
        async_remove_device=Mock(),
        devices={entry.id: entry for entry in entries},
    )

    monkeypatch.setattr(
        "custom_components.iam_air.dr.async_get",
        lambda _hass: registry,
    )
    removed = async_remove_stale_devices(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(entry_id="fake-entry"),  # type: ignore[arg-type]
        {"fake-active-iot-id"},
    )

    assert removed == 1
    registry.async_remove_device.assert_called_once_with("stale-registry-device")


def test_remove_stale_entities_uses_platform_active_unique_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Old platform entities disappear when the current TSL no longer exposes them."""
    entries = [
        SimpleNamespace(
            entity_id="switch.active",
            platform=DOMAIN,
            unique_id="fake-device_powerswitch",
        ),
        SimpleNamespace(
            entity_id="switch.stale",
            platform=DOMAIN,
            unique_id="fake-device_uvswitch",
        ),
        SimpleNamespace(
            entity_id="sensor.other_platform",
            platform="other_platform",
            unique_id="fake-device_other",
        ),
    ]
    registry = SimpleNamespace(async_remove=Mock())
    monkeypatch.setattr(
        "custom_components.iam_air.er.async_get",
        lambda _hass: registry,
    )
    monkeypatch.setattr(
        "custom_components.iam_air.er.async_entries_for_config_entry",
        lambda _registry, _entry_id: entries,
    )

    removed = async_remove_stale_entities(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(entry_id="fake-entry"),  # type: ignore[arg-type]
        {"fake-device_powerswitch"},
    )

    assert removed == 1
    registry.async_remove.assert_called_once_with("switch.stale")

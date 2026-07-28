"""Import smoke tests for Home Assistant platforms."""

import importlib

import pytest


@pytest.mark.parametrize(
    "module",
    (
        "custom_components.iam_air",
        "custom_components.iam_air.credentials",
        "custom_components.iam_air.cloud",
        "custom_components.iam_air.config_flow",
        "custom_components.iam_air.coordinator",
        "custom_components.iam_air.entity",
        "custom_components.iam_air.fan",
        "custom_components.iam_air.sensor",
        "custom_components.iam_air.switch",
    ),
)
def test_module_imports(module: str) -> None:
    """Every HA platform imports against the current HA version."""
    importlib.import_module(module)

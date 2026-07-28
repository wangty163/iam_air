"""Tests for config-flow credential handling."""

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from custom_components.iam_air.config_flow import user_schema
from custom_components.iam_air.const import CONF_APK_PATH


def test_schema_reuses_only_non_secret_defaults() -> None:
    """A retry can retain account fields without retaining secret inputs."""
    schema = user_schema(
        {
            CONF_USERNAME: "fake-account",
            CONF_APK_PATH: "/config/iam_air/xingou.apk",
        }
    )

    result = schema(
        {
            CONF_PASSWORD: "fake-password",
        }
    )

    assert result[CONF_USERNAME] == "fake-account"
    assert result[CONF_APK_PATH] == "/config/iam_air/xingou.apk"
    assert result[CONF_PASSWORD] == "fake-password"

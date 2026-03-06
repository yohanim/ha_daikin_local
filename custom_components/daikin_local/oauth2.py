"""OAuth2 implementation for Daikin Onecta."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_entry_oauth2_helper as config_entry_oauth2_helper

from .const import DAIKIN_ONECTA_AUTH_URL, DAIKIN_ONECTA_TOKEN_URL

async def async_register_implementation(hass: HomeAssistant) -> None:
    """Register Daikin Onecta implementation."""
    config_entry_oauth2_helper.async_register_implementation(
        hass,
        "daikin_local",
        config_entry_oauth2_helper.LocalOAuth2Implementation(
            hass,
            "daikin_local",
            "Daikin Onecta",
            DAIKIN_ONECTA_AUTH_URL,
            DAIKIN_ONECTA_TOKEN_URL,
        ),
    )

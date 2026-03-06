"""OAuth2 implementation for Daikin Onecta."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow

from .const import DAIKIN_ONECTA_AUTH_URL, DAIKIN_ONECTA_TOKEN_URL, DOMAIN

async def async_register_implementation(hass: HomeAssistant) -> None:
    """Register Daikin Onecta implementation."""
    # This allows the integration to use the "Application Credentials" configuration
    # where the user can enter their Client ID and Client Secret in the HA UI.
    config_entry_oauth2_flow.async_register_implementation(
        hass,
        DOMAIN,
        config_entry_oauth2_flow.LocalOAuth2Implementation(
            hass,
            DOMAIN,
            "Daikin Onecta",
            DAIKIN_ONECTA_AUTH_URL,
            DAIKIN_ONECTA_TOKEN_URL,
        ),
    )

"""OAuth2 implementation for Daikin Onecta."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

async def async_register_implementation(hass: HomeAssistant) -> None:
    """Register Daikin Onecta implementation."""
    # HA handles registration automatically through application_credentials.py
    pass

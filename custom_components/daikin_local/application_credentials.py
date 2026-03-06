"""Application credentials platform for Daikin Local."""

from homeassistant.components.application_credentials import AuthorizationServer
from homeassistant.core import HomeAssistant

from .const import DAIKIN_ONECTA_AUTH_URL, DAIKIN_ONECTA_TOKEN_URL

async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    """Return authorization server."""
    return AuthorizationServer(
        authorize_url=DAIKIN_ONECTA_AUTH_URL,
        token_url=DAIKIN_ONECTA_TOKEN_URL,
    )

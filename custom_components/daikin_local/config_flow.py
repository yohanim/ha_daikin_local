"""Config flow for the Daikin platform."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from aiohttp import ClientError, web_exceptions
from pydaikin.daikin_base import Appliance
from pydaikin.discovery import Discovery
from pydaikin.exceptions import DaikinException
from pydaikin.factory import DaikinFactory
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    callback,
)
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_TIMEOUT,
    CONF_UUID,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.util.ssl import client_context_no_verify

from .const import CONF_AUTO_HISTORY_SYNC, DOMAIN, KEY_MAC, TIMEOUT_SEC

_LOGGER = logging.getLogger(__name__)


class FlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the Daikin config flow."""
        self.host: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler()

    @property
    def schema(self) -> vol.Schema:
        """Return current schema."""
        return vol.Schema(
            {
                vol.Required(CONF_HOST, default=self.host): str,
                vol.Optional(CONF_API_KEY): str,
                vol.Optional(CONF_PASSWORD): str,
                vol.Optional(CONF_TIMEOUT, default=TIMEOUT_SEC): int,
            }
        )

    async def _create_entry(
        self,
        host: str,
        mac: str,
        key: str | None = None,
        uuid: str | None = None,
        password: str | None = None,
        timeout: int = TIMEOUT_SEC,
    ) -> ConfigFlowResult:
        """Register new entry."""
        if not self.unique_id:
            await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=host,
            data={
                CONF_HOST: host,
                KEY_MAC: mac,
                CONF_API_KEY: key,
                CONF_UUID: uuid,
                CONF_PASSWORD: password,
                CONF_TIMEOUT: timeout,
            },
        )

    async def _create_device(
        self,
        host: str,
        key: str | None = None,
        password: str | None = None,
        timeout: int = TIMEOUT_SEC,
    ) -> ConfigFlowResult:
        """Create device."""
        # BRP07Cxx devices needs uuid together with key
        if key:
            uuid = str(uuid4())
        else:
            uuid = None
            key = None

        if not password:
            password = None

        try:
            async with asyncio.timeout(timeout):
                device: Appliance = await DaikinFactory(
                    host,
                    async_get_clientsession(self.hass),
                    key=key,
                    uuid=uuid,
                    password=password,
                    ssl_context=client_context_no_verify(),
                )
        except (TimeoutError, ClientError):
            self.host = None
            return self.async_show_form(
                step_id="user",
                data_schema=self.schema,
                errors={"base": "cannot_connect"},
            )
        except web_exceptions.HTTPForbidden:
            return self.async_show_form(
                step_id="user",
                data_schema=self.schema,
                errors={"base": "invalid_auth"},
            )
        except DaikinException as daikin_exp:
            _LOGGER.error(daikin_exp)
            return self.async_show_form(
                step_id="user",
                data_schema=self.schema,
                errors={"base": "unknown"},
            )
        except Exception:
            _LOGGER.exception("Unexpected error creating device")
            return self.async_show_form(
                step_id="user",
                data_schema=self.schema,
                errors={"base": "unknown"},
            )

        mac = device.mac
        return await self._create_entry(host, mac, key, uuid, password, timeout)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """User initiated config flow."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=self.schema)
        if user_input.get(CONF_API_KEY) and user_input.get(CONF_PASSWORD):
            self.host = user_input[CONF_HOST]
            return self.async_show_form(
                step_id="user",
                data_schema=self.schema,
                errors={"base": "api_password"},
            )
        return await self._create_device(
            user_input[CONF_HOST],
            user_input.get(CONF_API_KEY),
            user_input.get(CONF_PASSWORD),
            user_input.get(CONF_TIMEOUT, TIMEOUT_SEC),
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Prepare configuration for a discovered Daikin device."""
        _LOGGER.debug("Zeroconf user_input: %s", discovery_info)
        devices = Discovery().poll(ip=discovery_info.host)
        if not devices:
            _LOGGER.debug(
                (
                    "Could not find MAC-address for %s, make sure the required UDP"
                    " ports are open (see integration documentation)"
                ),
                discovery_info.host,
            )
            return self.async_abort(reason="cannot_connect")
        await self.async_set_unique_id(next(iter(devices))[KEY_MAC])
        self._abort_if_unique_id_configured()
        self.host = discovery_info.host
        return await self.async_step_user()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user change host, credentials, and timeout for an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            form_key = (user_input.get(CONF_API_KEY) or "").strip()
            form_password = (user_input.get(CONF_PASSWORD) or "").strip()
            if form_key and form_password:
                errors["base"] = "api_password"
            else:
                host = user_input[CONF_HOST]
                timeout = user_input.get(CONF_TIMEOUT, TIMEOUT_SEC)
                if form_key:
                    key = form_key
                    uuid = str(uuid4())
                else:
                    key = entry.data.get(CONF_API_KEY)
                    uuid = entry.data.get(CONF_UUID)
                password = form_password if form_password else entry.data.get(CONF_PASSWORD)
                try:
                    async with asyncio.timeout(timeout):
                        device: Appliance = await DaikinFactory(
                            host,
                            async_get_clientsession(self.hass),
                            key=key,
                            uuid=uuid,
                            password=password,
                            ssl_context=client_context_no_verify(),
                        )
                except (TimeoutError, ClientError):
                    errors["base"] = "cannot_connect"
                except web_exceptions.HTTPForbidden:
                    errors["base"] = "invalid_auth"
                except DaikinException as daikin_exp:
                    _LOGGER.error(daikin_exp)
                    errors["base"] = "unknown"
                except Exception:
                    _LOGGER.exception("Unexpected error reconfiguring device")
                    errors["base"] = "unknown"
                else:
                    if device.mac != entry.data[KEY_MAC]:
                        errors["base"] = "wrong_device"
                    else:
                        return self.async_update_reload_and_abort(
                            entry,
                            data_updates={
                                CONF_HOST: host,
                                CONF_API_KEY: key,
                                CONF_UUID: uuid,
                                CONF_PASSWORD: password,
                                CONF_TIMEOUT: timeout,
                            },
                        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HOST, default=entry.data[CONF_HOST]
                ): str,
                vol.Optional(CONF_API_KEY): str,
                vol.Optional(CONF_PASSWORD): str,
                vol.Optional(
                    CONF_TIMEOUT,
                    default=entry.data.get(CONF_TIMEOUT, TIMEOUT_SEC),
                ): int,
            }
        )
        suggested = {
            CONF_HOST: entry.data[CONF_HOST],
            CONF_TIMEOUT: entry.data.get(CONF_TIMEOUT, TIMEOUT_SEC),
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )


class OptionsFlowHandler(OptionsFlow):
    """Handle options flow."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            # Merge so we only manage auto_history_sync here; do not wipe other keys.
            merged = {**self.config_entry.options, **user_input}
            return self.async_create_entry(title="", data=merged)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Optional(
                            CONF_AUTO_HISTORY_SYNC, default=False
                        ): cv.boolean,
                    }
                ),
                self.config_entry.options,
            ),
        )


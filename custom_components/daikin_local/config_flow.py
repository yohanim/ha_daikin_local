"""Config flow for the Daikin platform."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import ClientError
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
from homeassistant.const import CONF_HOST
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import (
    CONF_AUTO_HISTORY_SYNC,
    CONF_HISTORY_HOURS_TO_CORRECT,
    CONF_HISTORY_SKIP_EXTRA_HOURS,
    CONF_INSERT_MISSING,
    CONF_TIMEOUT,
    DOMAIN,
    KEY_MAC,
    TIMEOUT_SEC,
)

_LOGGER = logging.getLogger(__name__)


class FlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 4

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
                vol.Optional(CONF_TIMEOUT, default=TIMEOUT_SEC): int,
            }
        )

    async def _create_entry(
        self,
        host: str,
        mac: str,
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
                CONF_TIMEOUT: timeout,
            },
        )

    async def _create_device(
        self,
        host: str,
        timeout: int = TIMEOUT_SEC,
    ) -> ConfigFlowResult:
        """Create device."""
        try:
            async with asyncio.timeout(timeout):
                device: Appliance = await DaikinFactory(
                    host,
                    async_get_clientsession(self.hass),
                )
        except (TimeoutError, ClientError):
            self.host = None
            return self.async_show_form(
                step_id="user",
                data_schema=self.schema,
                errors={"base": "cannot_connect"},
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
        return await self._create_entry(host, mac, timeout)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """User initiated config flow."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=self.schema)
        return await self._create_device(
            user_input[CONF_HOST],
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
        """Let the user change host and timeout for an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            timeout = user_input.get(CONF_TIMEOUT, TIMEOUT_SEC)
            try:
                async with asyncio.timeout(timeout):
                    device: Appliance = await DaikinFactory(
                        host,
                        async_get_clientsession(self.hass),
                    )
            except (TimeoutError, ClientError):
                errors["base"] = "cannot_connect"
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
                            CONF_TIMEOUT: timeout,
                        },
                    )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HOST, default=entry.data[CONF_HOST]
                ): str,
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

        suggested = {
            CONF_TIMEOUT: self.config_entry.options.get(CONF_TIMEOUT)
            or self.config_entry.data.get(CONF_TIMEOUT, TIMEOUT_SEC),
            CONF_AUTO_HISTORY_SYNC: self.config_entry.options.get(
                CONF_AUTO_HISTORY_SYNC, False
            ),
            CONF_INSERT_MISSING: self.config_entry.options.get(
                CONF_INSERT_MISSING, False
            ),
            CONF_HISTORY_SKIP_EXTRA_HOURS: self.config_entry.options.get(
                CONF_HISTORY_SKIP_EXTRA_HOURS, 1
            ),
            CONF_HISTORY_HOURS_TO_CORRECT: self.config_entry.options.get(
                CONF_HISTORY_HOURS_TO_CORRECT, 3
            ),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Optional(CONF_TIMEOUT, default=TIMEOUT_SEC): int,
                        vol.Optional(CONF_AUTO_HISTORY_SYNC, default=False): cv.boolean,
                        vol.Optional(CONF_INSERT_MISSING, default=False): cv.boolean,
                        vol.Optional(
                            CONF_HISTORY_SKIP_EXTRA_HOURS,
                            default=1,
                        ): selector.NumberSelector(
                            {
                                "min": 1,
                                "max": 12,
                                "step": 1,
                                "mode": "slider",
                                "unit_of_measurement": "h",
                            }
                        ),
                        vol.Optional(
                            CONF_HISTORY_HOURS_TO_CORRECT,
                            default=3,
                        ): selector.NumberSelector(
                            {
                                "min": 1,
                                "max": 24,
                                "step": 1,
                                "mode": "slider",
                                "unit_of_measurement": "h",
                            }
                        ),
                    }
                ),
                suggested,
            ),
        )


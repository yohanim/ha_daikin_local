"""Base entity for Daikin."""

from collections.abc import Awaitable, Callable

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from pydaikin.exceptions import (
    DaikinCommandRejected,
    DaikinException,
    DaikinVerificationError,
)

from .const import DOMAIN
from .coordinator import DaikinCoordinator
from .pure import poll_error_translation_error


async def async_execute_daikin_command(
    coordinator: DaikinCoordinator, command: Callable[[], Awaitable[None]]
) -> None:
    """Run a pydaikin command through the coordinator's shared lock, bounded by a timeout.

    Shared by entity commands (via ``DaikinEntity._async_execute_command``) and the
    service handlers in :mod:`.services`, so that every write to the device — like
    polling — cannot hold the communication lock forever and starve subsequent polls.
    Timeouts and pydaikin errors are translated into ``HomeAssistantError`` so the UI
    shows a clear message instead of a raw exception.

    Since pydaikin 2.22.1 a write the adapter answers with a non-OK ``ret`` raises
    ``DaikinCommandRejected`` instead of passing silently, and a half-degree
    setpoint that reads back differently raises ``DaikinVerificationError``. The
    unit answered in both cases, so they get their own message rather than the
    generic communication error.
    """
    try:
        await coordinator.async_execute_command(command)
    except DaikinCommandRejected as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_rejected",
            translation_placeholders={"ret": str(err.ret)},
        ) from err
    except DaikinVerificationError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="setpoint_not_applied",
            translation_placeholders={
                "requested": str(err.requested),
                "actual": str(err.actual),
            },
        ) from err
    except TimeoutError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="error_communicating",
            translation_placeholders={
                "error": poll_error_translation_error(err, is_daikin_exception=False)
            },
        ) from err
    except DaikinException as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="error_communicating",
            translation_placeholders={
                "error": poll_error_translation_error(err, is_daikin_exception=True)
            },
        ) from err


class DaikinEntity(CoordinatorEntity[DaikinCoordinator]):
    """Base entity for Daikin."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DaikinCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.device = coordinator.device
        info = self.device.values
        ver = info.get("ver")
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, self.device.mac)},
            manufacturer="Daikin",
            model=info.get("model"),
            name=info.get("name"),
            sw_version=ver.replace("_", ".") if ver else None,
        )

    async def _async_execute_command(
        self, command: Callable[[], Awaitable[None]]
    ) -> None:
        """Send a command to the device, give optimistic UI feedback, then refresh.

        ``async_write_ha_state`` runs immediately after the command succeeds (before
        the slower ``async_refresh`` poll completes) so the UI reflects the change
        without waiting for the next full state read.
        """
        await async_execute_daikin_command(self.coordinator, command)
        self.async_write_ha_state()
        await self.coordinator.async_refresh()

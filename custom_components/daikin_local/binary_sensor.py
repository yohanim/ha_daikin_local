"""Support for Daikin AC binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ATTR_COMPRESSOR_RUNNING
from .coordinator import DaikinConfigEntry, DaikinCoordinator
from .entity import DaikinEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaikinConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Daikin binary sensors based on config_entry."""
    coordinator = entry.runtime_data
    # BRP084 only (pydaikin reads the outdoor unit's e_2006 run flag); other
    # adapters do not define the support flag.
    if getattr(coordinator.device, "support_compressor_running", False):
        async_add_entities([DaikinCompressorRunningSensor(coordinator)])


class DaikinCompressorRunningSensor(DaikinEntity, BinarySensorEntity):
    """Whether the outdoor compressor is running."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_translation_key = ATTR_COMPRESSOR_RUNNING
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: DaikinCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self.device.mac}-{ATTR_COMPRESSOR_RUNNING}"

    @property
    def suggested_object_id(self) -> str | None:
        """Suffix only: Home Assistant prepends the device slug."""
        return ATTR_COMPRESSOR_RUNNING

    @property
    def is_on(self) -> bool | None:
        """Return True while the compressor runs."""
        return self.device.compressor_running

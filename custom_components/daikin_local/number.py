"""Support for Daikin number entities."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DaikinConfigEntry, DaikinCoordinator
from .entity import DaikinEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaikinConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Daikin number entities based on config_entry."""
    daikin_api = entry.runtime_data
    numbers: list[NumberEntity] = []
    if daikin_api.device.support_demand_control:
        numbers.append(DaikinDemandControlMaxPowerNumber(daikin_api))
    async_add_entities(numbers)


class DaikinDemandControlMaxPowerNumber(DaikinEntity, NumberEntity):
    """Max power percentage for demand control (BRP069, protocol v3+ only)."""

    _attr_translation_key = "demand_control_max_power"
    _attr_entity_registry_enabled_default = False
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: DaikinCoordinator) -> None:
        """Initialize number."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self.device.mac}-demand_control_max_pow"

    @property
    def suggested_object_id(self) -> str | None:
        return "demand_control_max_power"

    @property
    def native_value(self) -> float | None:
        """Return the current max power percentage."""
        max_pow = self.device.get_demand_control().get("max_pow")
        return None if max_pow is None else float(max_pow)

    async def async_set_native_value(self, value: float) -> None:
        """Set the max power percentage."""
        async with self.coordinator.pydaikin_communication_lock:
            await self.device.set_demand_control(max_pow=int(value))
        self.async_write_ha_state()
        await self.coordinator.async_refresh()

"""Support for Daikin AC sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ATTR_COMPRESSOR_FREQUENCY,
    ATTR_COOL_ENERGY,
    ATTR_ENERGY_TODAY,
    ATTR_HEAT_ENERGY,
    ATTR_HUMIDITY,
    ATTR_INSIDE_TEMPERATURE,
    ATTR_OUTSIDE_TEMPERATURE,
    ATTR_TARGET_HUMIDITY,
    ATTR_TOTAL_ENERGY_TODAY,
    ATTR_TOTAL_POWER,
)
from .coordinator import DaikinConfigEntry, DaikinCoordinator, DaikinData
from .entity import DaikinEntity


@dataclass(frozen=True, kw_only=True)
class DaikinSensorEntityDescription(SensorEntityDescription):
    """Describes Daikin sensor entity backed by coordinator data snapshot."""

    value_func: Callable[[DaikinData], float | None]


@dataclass(frozen=True, kw_only=True)
class DaikinDiagnosticSensorEntityDescription(SensorEntityDescription):
    """Diagnostics: integer counters read live from the coordinator (not from DaikinData)."""

    value_from_coordinator: Callable[[DaikinCoordinator], int]


SENSOR_TYPES: tuple[DaikinSensorEntityDescription, ...] = (
    DaikinSensorEntityDescription(
        key=ATTR_INSIDE_TEMPERATURE,
        translation_key="inside_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_func=lambda data: data.appliance.inside_temperature,
    ),
    DaikinSensorEntityDescription(
        key=ATTR_OUTSIDE_TEMPERATURE,
        translation_key="outside_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_func=lambda data: data.appliance.outside_temperature,
    ),
    DaikinSensorEntityDescription(
        key=ATTR_HUMIDITY,
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_func=lambda data: data.appliance.humidity,
    ),
    DaikinSensorEntityDescription(
        key=ATTR_TARGET_HUMIDITY,
        translation_key="target_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        # pydaikin exposes the configured target humidity on some models.
        # If not available, fall back to the current humidity.
        value_func=lambda data: (
            data.appliance.target_humidity
            if getattr(data.appliance, "target_humidity", None) is not None
            else data.appliance.humidity
        ),
    ),
    DaikinSensorEntityDescription(
        key=ATTR_TOTAL_POWER,
        translation_key="compressor_estimated_power_consumption",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        entity_registry_enabled_default=False,
        value_func=lambda data: round(
            data.appliance.current_total_power_consumption, 2
        ),
    ),
    DaikinSensorEntityDescription(
        key=ATTR_COOL_ENERGY,
        translation_key="cool_energy_consumption",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        entity_registry_enabled_default=False,
        value_func=lambda data: round(data.today_cool_energy, 2),
    ),
    DaikinSensorEntityDescription(
        key=ATTR_HEAT_ENERGY,
        translation_key="heat_energy_consumption",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        entity_registry_enabled_default=False,
        value_func=lambda data: round(data.today_heat_energy, 2),
    ),
    DaikinSensorEntityDescription(
        key=ATTR_ENERGY_TODAY,
        translation_key="energy_consumption",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_func=lambda data: round(data.appliance.today_energy_consumption, 2),
    ),
    DaikinSensorEntityDescription(
        key=ATTR_COMPRESSOR_FREQUENCY,
        translation_key="compressor_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        entity_registry_enabled_default=False,
        value_func=lambda data: data.appliance.compressor_frequency,
    ),
    DaikinSensorEntityDescription(
        key=ATTR_TOTAL_ENERGY_TODAY,
        translation_key="compressor_energy_consumption",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        entity_registry_enabled_default=False,
        value_func=lambda data: round(data.calculated_total_energy_today, 2),
    ),
)

DIAGNOSTIC_SENSOR_TYPES: tuple[DaikinDiagnosticSensorEntityDescription, ...] = (
    DaikinDiagnosticSensorEntityDescription(
        key="pydaikin_daily_poll_errors",
        translation_key="pydaikin_daily_poll_errors",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=None,
        entity_registry_enabled_default=False,
        value_from_coordinator=lambda c: c.daily_polling_error_count,
    ),
    DaikinDiagnosticSensorEntityDescription(
        key="pydaikin_daily_state_poll_errors",
        translation_key="pydaikin_daily_state_poll_errors",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=None,
        entity_registry_enabled_default=False,
        value_from_coordinator=lambda c: c.daily_state_polling_error_count,
    ),
    DaikinDiagnosticSensorEntityDescription(
        key="pydaikin_daily_energy_poll_errors",
        translation_key="pydaikin_daily_energy_poll_errors",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=None,
        entity_registry_enabled_default=False,
        value_from_coordinator=lambda c: c.daily_energy_polling_error_count,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaikinConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Daikin climate based on config_entry."""
    coordinator = entry.runtime_data
    device = coordinator.device

    entities: list[DaikinSensor | DaikinDiagnosticSensor] = []

    for description in SENSOR_TYPES:
        supported = False
        if description.key == ATTR_INSIDE_TEMPERATURE:
            supported = True
        elif description.key == ATTR_OUTSIDE_TEMPERATURE:
            supported = device.support_outside_temperature
        elif description.key in (
            ATTR_ENERGY_TODAY,
            ATTR_COOL_ENERGY,
            ATTR_HEAT_ENERGY,
            ATTR_TOTAL_POWER,
            ATTR_TOTAL_ENERGY_TODAY,
        ):
            supported = device.support_energy_consumption
        elif description.key in (ATTR_HUMIDITY, ATTR_TARGET_HUMIDITY):
            supported = device.support_humidity
        elif description.key == ATTR_COMPRESSOR_FREQUENCY:
            supported = device.support_compressor_frequency

        if supported:
            entities.append(DaikinSensor(coordinator, description))

    for description in DIAGNOSTIC_SENSOR_TYPES:
        entities.append(DaikinDiagnosticSensor(coordinator, description))

    async_add_entities(entities)


class DaikinSensor(DaikinEntity, SensorEntity):
    """Representation of a Sensor."""

    entity_description: DaikinSensorEntityDescription

    def __init__(
        self,
        coordinator: DaikinCoordinator,
        description: DaikinSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{self.device.mac}-{description.key}"
        # Explicit so HA always resolves entity.sensor.<translation_key> names (not only device name).
        self._attr_translation_key = description.translation_key

    @property
    def suggested_object_id(self) -> str | None:
        """Suffix only: Home Assistant prepends the device slug to suggested_object_id."""
        return self.entity_description.key

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_func(self.coordinator.data)


class DaikinDiagnosticSensor(DaikinEntity, SensorEntity):
    """Diagnostics counters: values come from the coordinator, not the data snapshot."""

    entity_description: DaikinDiagnosticSensorEntityDescription

    def __init__(
        self,
        coordinator: DaikinCoordinator,
        description: DaikinDiagnosticSensorEntityDescription,
    ) -> None:
        """Initialize the diagnostic sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{self.device.mac}-{description.key}"
        self._attr_translation_key = description.translation_key

    @property
    def suggested_object_id(self) -> str | None:
        """Suffix only: HA prepends device slug."""
        return self.entity_description.key

    @property
    def native_value(self) -> int:
        """Return the current diagnostic counter (always defined; defaults apply before first poll)."""
        return self.entity_description.value_from_coordinator(self.coordinator)

"""Constants for Daikin."""

DOMAIN = "daikin_local"

ATTR_TARGET_TEMPERATURE = "target_temperature"
ATTR_INSIDE_TEMPERATURE = "inside_temperature"
ATTR_OUTSIDE_TEMPERATURE = "outside_temperature"

ATTR_TARGET_HUMIDITY = "target_humidity"
ATTR_HUMIDITY = "humidity"

ATTR_COMPRESSOR_FREQUENCY = "compressor_frequency"

ATTR_ENERGY_TODAY = "energy_today"
ATTR_COOL_ENERGY = "cool_energy"
ATTR_HEAT_ENERGY = "heat_energy"

ATTR_TOTAL_POWER = "total_power"
ATTR_TOTAL_ENERGY_TODAY = "total_energy_today"

ATTR_STATE_ON = "on"
ATTR_STATE_OFF = "off"

KEY_MAC = "mac"

CONF_TIMEOUT = "timeout"
# When True, periodically inject Daikin hourly energy into recorder LTS (opt-in).
CONF_AUTO_HISTORY_SYNC = "auto_history_sync"

ZONE_NAME_UNCONFIGURED = "-"

TIMEOUT_SEC = 30

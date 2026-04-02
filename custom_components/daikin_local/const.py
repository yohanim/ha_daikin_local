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
# When True, history sync may INSERT missing hourly LTS rows (can conflict with recorder).
CONF_INSERT_MISSING = "insert_missing"

# History correction window:
# - skip_extra_hours: number of *additional* most recent local hours to ignore,
#   besides the current hour which is always skipped.
#   Example: 1 = skip current hour + 1 previous hour (effectively skip 2 hours).
# - hours_to_correct: number of hours to attempt correction for, right before the skipped range.
CONF_HISTORY_SKIP_EXTRA_HOURS = "history_skip_extra_hours"
CONF_HISTORY_HOURS_TO_CORRECT = "history_hours_to_correct"

ZONE_NAME_UNCONFIGURED = "-"

TIMEOUT_SEC = 30

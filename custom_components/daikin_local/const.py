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

# Entry data flags (set at config / reconfigure time)
KEY_IS_BRP069 = "is_brp069"
KEY_SUPPORTS_ENERGY = "supports_energy"

# Legacy single field (v4 and below); migrated to connection_timeout + poll_interval_sec.
CONF_TIMEOUT = "timeout"
# Max time for a single HTTP request to the adapter (asyncio.timeout around pydaikin calls).
CONF_CONNECTION_TIMEOUT = "connection_timeout"
# How often the DataUpdateCoordinator runs when not using BRP069 energy split scheduling.
CONF_POLL_INTERVAL_SEC = "poll_interval_sec"
# When True, periodically inject Daikin hourly energy into recorder LTS (opt-in).
CONF_AUTO_HISTORY_SYNC = "auto_history_sync"
# When True, history sync may INSERT missing hourly LTS rows (can conflict with recorder).
CONF_INSERT_MISSING = "insert_missing"

# BRP069 polling split:
# - state domain: temperatures/humidity/mode, etc. (sensor/control endpoints)
# - energy domain: consumption totals and arrays (day/week power endpoints)
CONF_POLL_INTERVAL_STATE_SEC = "poll_interval_state_sec"
CONF_POLL_INTERVAL_ENERGY_SEC = "poll_interval_energy_sec"

# Group ID used to aggregate totals across multiple adapters (e.g. two BRP069 on same system).
CONF_ENERGY_GROUP_ID = "energy_group_id"

# When set on one entry within an energy_group_id, only those marked as master will run
# group-scoped total history sync (avoids duplicate corrections across the group).
CONF_ENERGY_GROUP_TOTAL_HISTORY_MASTER = "energy_group_total_history_master"

# History correction window:
# - skip_extra_hours: number of *additional* most recent local hours to ignore,
#   besides the current hour which is always skipped.
#   Example: 1 = skip current hour + 1 previous hour (effectively skip 2 hours).
# - hours_to_correct: number of hours to attempt correction for, right before the skipped range.
CONF_HISTORY_SKIP_EXTRA_HOURS = "history_skip_extra_hours"
CONF_HISTORY_HOURS_TO_CORRECT = "history_hours_to_correct"

ZONE_NAME_UNCONFIGURED = "-"

TIMEOUT_SEC = 30

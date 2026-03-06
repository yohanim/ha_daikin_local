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
KEY_IP = "ip"

CONF_TIMEOUT = "timeout"
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_CLOUD_DEVICE_ID = "cloud_device_id"

CONF_CLOUD_SCAN_INTERVAL_DAY = "cloud_scan_interval_day"
CONF_CLOUD_SCAN_INTERVAL_NIGHT = "cloud_scan_interval_night"
CONF_CLOUD_DAY_START = "cloud_day_start"
CONF_CLOUD_DAY_END = "cloud_day_end"

DEFAULT_CLOUD_SCAN_INTERVAL_DAY = 10  # minutes
DEFAULT_CLOUD_SCAN_INTERVAL_NIGHT = 60  # minutes
DEFAULT_CLOUD_DAY_START = "07:00"
DEFAULT_CLOUD_DAY_END = "23:00"

ZONE_NAME_UNCONFIGURED = "-"

TIMEOUT_SEC = 30

# Cloud API
DAIKIN_ONECTA_API_URL = "https://api.onecta.daikineurope.com/v1"
DAIKIN_ONECTA_AUTH_URL = "https://api.onecta.daikineurope.com/v1/oidc/authorize"
DAIKIN_ONECTA_TOKEN_URL = "https://api.onecta.daikineurope.com/v1/oidc/token"
SWING_WINDNICE = "windnice"

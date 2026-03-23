"""Constants for the HomeSecure HA integration."""

DOMAIN = "homesecure"

# ── These mirror the container's state strings exactly ──────────────────────
# Kept here so the rest of the integration can do `from .const import …`
# without hard-coding strings.

STATE_ALARM_DISARMED   = "disarmed"
STATE_ALARM_ARMING     = "arming"
STATE_ALARM_ARMED_HOME = "armed_home"
STATE_ALARM_ARMED_AWAY = "armed_away"
STATE_ALARM_PENDING    = "pending"
STATE_ALARM_TRIGGERED  = "triggered"

# ── Config entry keys ────────────────────────────────────────────────────────
CONF_CONTAINER_URL = "container_url"
CONF_API_TOKEN     = "api_token"
CONF_SERVICE_PIN   = "service_pin"   # auto-generated; used to arm from HA UI

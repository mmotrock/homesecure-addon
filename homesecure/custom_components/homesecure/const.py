"""Constants for the HomeSecure integration."""

DOMAIN = "homesecure"

# Alarm states (defined as strings for compatibility)
STATE_ALARM_DISARMED = "disarmed"
STATE_ALARM_ARMED_HOME = "armed_home"
STATE_ALARM_ARMED_AWAY = "armed_away"
STATE_ALARM_PENDING = "pending"
STATE_ALARM_TRIGGERED = "triggered"
STATE_ALARM_ARMING = "arming"

# Configuration
CONF_DB_PATH = "db_path"
CONF_ENTRY_DELAY = "entry_delay"
CONF_EXIT_DELAY = "exit_delay"
CONF_ALARM_DURATION = "alarm_duration"
CONF_TRIGGER_DOORS = "trigger_doors"
CONF_NOTIFICATION_MOBILE = "notification_mobile"
CONF_NOTIFICATION_SMS = "notification_sms"
CONF_SMS_NUMBERS = "sms_numbers"
CONF_LOCK_DELAY_HOME = "lock_delay_home"
CONF_LOCK_DELAY_AWAY = "lock_delay_away"
CONF_CLOSE_DELAY_HOME = "close_delay_home"
CONF_CLOSE_DELAY_AWAY = "close_delay_away"

# Defaults
DEFAULT_ENTRY_DELAY = 30  # seconds
DEFAULT_EXIT_DELAY = 60  # seconds
DEFAULT_ALARM_DURATION = 300  # seconds (5 minutes)

# States
STATE_ARMING = "arming"

# Alarm modes
MODE_ARMED_HOME = "armed_home"
MODE_ARMED_AWAY = "armed_away"
MODE_DISARMED = "disarmed"

# Events
EVENT_ALARM_ARMED = f"{DOMAIN}_armed"
EVENT_ALARM_DISARMED = f"{DOMAIN}_disarmed"
EVENT_ALARM_TRIGGERED = f"{DOMAIN}_triggered"
EVENT_ALARM_DURESS = f"{DOMAIN}_duress_code_used"
EVENT_FAILED_AUTH = f"{DOMAIN}_failed_auth"

# Attributes
ATTR_CHANGED_BY = "changed_by"
ATTR_CODE_FORMAT = "code_format"
ATTR_ZONES_BYPASSED = "zones_bypassed"
ATTR_ACTIVE_ZONES = "active_zones"
ATTR_FAILED_ATTEMPTS = "failed_attempts"

# Services
SERVICE_ARM_AWAY = "arm_away"
SERVICE_ARM_HOME = "arm_home"
SERVICE_DISARM = "disarm"
SERVICE_ADD_USER = "add_user"
SERVICE_REMOVE_USER = "remove_user"
SERVICE_BYPASS_ZONE = "bypass_zone"
SERVICE_UPDATE_CONFIG = "update_config"

# Database tables
TABLE_USERS = "alarm_users"
TABLE_CONFIG = "alarm_config"
TABLE_EVENTS = "alarm_events"
TABLE_FAILED_ATTEMPTS = "failed_attempts"
TABLE_ZONES = "alarm_zones"

# Zone types
ZONE_TYPE_PERIMETER = "perimeter"
ZONE_TYPE_INTERIOR = "interior"
ZONE_TYPE_ENTRY = "entry"

# Maximum failed attempts before lockout
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION = 300  # seconds (5 minutes)
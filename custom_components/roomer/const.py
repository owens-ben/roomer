"""Constants for Roomer integration."""

from datetime import timedelta

DOMAIN = "roomer"

# Configuration keys
CONF_PROVIDER = "provider"
CONF_URL = "url"
CONF_MODEL = "model"
CONF_API_KEY = "api_key"  # For OpenAI, Anthropic, etc.
CONF_POLL_INTERVAL = "poll_interval"
CONF_PERSONS = "persons"
CONF_PETS = "pets"
CONF_ROOMS = "rooms"

# Room-entity mapping configuration
# Maps rooms to lists of entities that indicate activity in that room
CONF_ROOM_ENTITIES = "room_entities"  # Dict[room_name, List[entity_id]]

# Optional room -> Home Assistant area mapping, e.g. {"office": "area_id"}
CONF_ROOM_AREAS = "room_areas"

# What a mapped detection entity counts for: only people, only animals, or both
DETECTS_PERSON = "person"
DETECTS_ANIMAL = "animal"
DETECTS_ANY = "any"
DETECTS_OPTIONS = [DETECTS_ANY, DETECTS_PERSON, DETECTS_ANIMAL]

# Entity type hints - what kind of signal does this entity provide?
ENTITY_HINT_MOTION = "motion"  # Motion sensors
ENTITY_HINT_MEDIA = "media"  # Media players (TV, speakers)
ENTITY_HINT_LIGHT = "light"  # Lights
ENTITY_HINT_COMPUTER = "computer"  # PC/workstation indicators
ENTITY_HINT_CAMERA = "camera"  # Camera with AI detection
ENTITY_HINT_APPLIANCE = "appliance"  # Other appliances

ENTITY_HINTS = [
    ENTITY_HINT_MOTION,
    ENTITY_HINT_MEDIA,
    ENTITY_HINT_LIGHT,
    ENTITY_HINT_COMPUTER,
    ENTITY_HINT_CAMERA,
    ENTITY_HINT_APPLIANCE,
]

# Confidence weights for different entity types (can be overridden in options)
CONF_CONFIDENCE_WEIGHTS = "confidence_weights"
DEFAULT_CONFIDENCE_WEIGHTS = {
    ENTITY_HINT_CAMERA: 0.95,  # Camera AI detection is very reliable
    ENTITY_HINT_COMPUTER: 0.85,  # PC actively in use - very strong for office
    ENTITY_HINT_MEDIA: 0.80,  # Media playing is strong
    ENTITY_HINT_MOTION: 0.60,  # Motion sensor
    ENTITY_HINT_APPLIANCE: 0.50,  # Appliance in use
    ENTITY_HINT_LIGHT: 0.35,  # Light on - moderate indicator (increased from 0.25)
    "presence": 0.70,  # BLE/WiFi presence
    "door": 0.40,  # Door recently opened
    "climate": 0.20,  # Climate change - very weak
    "llm_reasoning": 0.50,  # LLM text reasoning
    "habit": 0.35,  # Habit-based prediction
}

# Person-device ownership mapping
# Maps person names to their "owned" entities (e.g., their PC, their phone tracker)
CONF_PERSON_DEVICES = "person_devices"  # Dict[person_name, List[entity_id]]

# Vision configuration keys
CONF_VISION_MODEL = "vision_model"

# Provider types
PROVIDER_OLLAMA = "ollama"
PROVIDER_CREWAI = "crewai"  # Uses CrewAI API with Claude/Ollama
PROVIDER_OPENAI = "openai"  # Stubbed
PROVIDER_ANTHROPIC = "anthropic"  # Stubbed

SUPPORTED_PROVIDERS = [PROVIDER_OLLAMA, PROVIDER_CREWAI]
ALL_PROVIDERS = [PROVIDER_OLLAMA, PROVIDER_CREWAI, PROVIDER_OPENAI, PROVIDER_ANTHROPIC]

# CrewAI defaults
DEFAULT_CREWAI_URL = "http://localhost:8502"
DEFAULT_CREWAI_MODEL = "sonnet"  # "haiku", "sonnet", or "opus"

# Defaults
DEFAULT_PROVIDER = PROVIDER_OLLAMA
DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"
DEFAULT_POLL_INTERVAL = 10  # seconds
DEFAULT_VISION_MODEL = "moondream"  # Faster than llava:7b (~5-15s vs ~50-60s)
DEFAULT_VISION_ENABLED = False

# Entity types
ENTITY_TYPE_PERSON = "person"
ENTITY_TYPE_PET = "pet"

# Valid room states (defaults, users can add custom rooms)
VALID_ROOMS = ["office", "living_room", "bedroom", "kitchen", "bathroom", "entry", "away", "unknown"]

# Special room values
ROOM_AWAY = "away"
ROOM_UNKNOWN = "unknown"

# Device tracker states
DEVICE_TRACKER_HOME = "home"
DEVICE_TRACKER_NOT_HOME = "not_home"
DEVICE_TRACKER_UNAVAILABLE = "unavailable"

# Confidence for device tracker based away detection
DEVICE_TRACKER_AWAY_CONFIDENCE = 0.95

# Confidence for room-level device presence (Bermuda, ESPresense, room-assistant, etc.)
DEVICE_ROOM_CONFIDENCE = 0.90  # All of the person's located devices report the same room
DEVICE_ROOM_SPLIT_CONFIDENCE = 0.70  # Their devices report different rooms

# Attributes
ATTR_CONFIDENCE = "confidence"
ATTR_LAST_SEEN = "last_seen"
ATTR_INDICATORS = "indicators"
ATTR_RAW_RESPONSE = "raw_response"
ATTR_SOURCE = "source"
ATTR_CANDIDATE_ROOMS = "candidate_rooms"
ATTR_LAST_CHANGED_REASON = "last_changed_reason"
ATTR_ROOM_AREA_ID = "room_area_id"
ATTR_VISION_IDENTIFIED = "vision_identified"
ATTR_VISION_CONFIDENCE = "vision_confidence"

# Storage management
CONF_RETENTION_DAYS = "retention_days"
CONF_MAX_FILE_SIZE_MB = "max_file_size_mb"
DEFAULT_RETENTION_DAYS = 30
DEFAULT_MAX_FILE_SIZE_MB = 100

# Learning configuration
CONF_LEARNING_ENABLED = "learning_enabled"
DEFAULT_LEARNING_ENABLED = True
HABIT_SAVE_INTERVAL = timedelta(minutes=15)

# Notification configuration
CONF_NOTIFICATIONS_ENABLED = "notifications_enabled"
DEFAULT_NOTIFICATIONS_ENABLED = True

# LLM request timeout
CONF_TIMEOUT = "llm_timeout"
DEFAULT_TIMEOUT = 30  # seconds

# Where a room guess came from (the ``source`` attribute)
SOURCE_LLM = "llm"
SOURCE_SENSOR = "sensor"
SOURCE_PRIOR = "prior"  # No active clue: a time-of-day guess
SOURCE_STICKY = "sticky"  # No active clue: still where they were last seen
SOURCE_MANUAL = "manual_correction"

# A quiet house gives only a prior, so keep its confidence low
PRIOR_MAX_CONFIDENCE = 0.25
PRIOR_INDICATOR = "No active clues; time-of-day guess"

# "Stay where last seen": a clue from the last STICKY_MAX_AGE seconds keeps the
# person in that room. Sticky confidence starts at the clue's confidence, raised
# to STICKY_BASE_MIN (a single sensor scores low on the combiner's scale but is
# still the best evidence there is) and capped at STICKY_MAX_CONFIDENCE, then
# halves every STICKY_HALF_LIFE seconds. Below STICKY_MIN_CONFIDENCE it is
# dropped in favour of the prior. Clues scoring under STRONG_CLUE_MIN_CONFIDENCE
# (an LLM guess with nothing behind it) are not remembered.
STICKY_HALF_LIFE = 3600.0
STICKY_MAX_AGE = 3 * 3600.0
STICKY_BASE_MIN = 0.5
STICKY_MAX_CONFIDENCE = 0.7
STICKY_MIN_CONFIDENCE = 0.15
STRONG_CLUE_MIN_CONFIDENCE = 0.15


def presence_sensor_unique_id(entity_type: str, name: str) -> str:
    """Unique id of the ``sensor.{name}_room`` entity of a person or pet."""
    return f"{DOMAIN}_{entity_type}_{name.lower().replace(' ', '_')}_room"

"""Constants for the Home Assistant Personal Assistant integration."""

DOMAIN = "ha_personal_assistant"
PLATFORMS = []

# Config keys
CONF_OLLAMA_URL = "ollama_url"
CONF_OLLAMA_MODEL = "ollama_model"
CONF_OLLAMA_EMBEDDING_MODEL = "ollama_embedding_model"
CONF_CLOUD_LLM_PROVIDER = "cloud_llm_provider"
CONF_CLOUD_LLM_API_KEY = "cloud_llm_api_key"
CONF_CLOUD_LLM_MODEL = "cloud_llm_model"
CONF_CLOUD_LLM_SEND_PROFILE = "cloud_llm_send_profile"
CONF_CLOUD_LLM_SEND_HA_STATE = "cloud_llm_send_ha_state"
CONF_AGENT_PERSONA = "agent_persona"
CONF_INFLUXDB_URL = "influxdb_url"
CONF_INFLUXDB_TOKEN = "influxdb_token"
CONF_INFLUXDB_ORG = "influxdb_org"
CONF_INFLUXDB_BUCKET = "influxdb_bucket"
CONF_BLOCKED_KEYWORDS = "blocked_keywords"
CONF_SESSION_TIMEOUT_MINUTES = "session_timeout_minutes"
CONF_CONTEXT_BUDGET = "context_budget"
CONF_ALLOWED_DOMAINS = "allowed_domains"
CONF_RESTRICTED_DOMAINS = "restricted_domains"
CONF_BLOCKED_DOMAINS = "blocked_domains"
CONF_REQUIRE_CONFIRMATION_SERVICES = "require_confirmation_services"

# Defaults
DEFAULT_OLLAMA_URL = "http://192.168.1.97:11434"
DEFAULT_OLLAMA_MODEL = "gpt-oss:20b"
DEFAULT_OLLAMA_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_SESSION_TIMEOUT_MINUTES = 30
DEFAULT_CONTEXT_BUDGET = 6000
DEFAULT_INFLUXDB_URL = "http://influx.internal"

DEFAULT_AGENT_PERSONA = (
    "You are a helpful, friendly personal assistant integrated with Home Assistant. "
    "You can control smart home devices, answer questions about the home, search the web, "
    "and learn user preferences over time. Be concise but thorough."
)

DEFAULT_ALLOWED_DOMAINS = "*"
DEFAULT_RESTRICTED_DOMAINS = ["lock", "camera"]
DEFAULT_BLOCKED_DOMAINS = ["homeassistant"]
DEFAULT_REQUIRE_CONFIRMATION_SERVICES = [
    "lock.unlock",
    "lock.lock",
    "camera.turn_on",
    "camera.turn_off",
    "camera.enable_motion_detection",
    "camera.disable_motion_detection",
]

# Cloud LLM provider options
CLOUD_LLM_NONE = "none"
CLOUD_LLM_OPENAI = "openai"
CLOUD_LLM_GEMINI = "gemini"

# Sensitivity levels
SENSITIVITY_PUBLIC = "public"
SENSITIVITY_PRIVATE = "private"
SENSITIVITY_SENSITIVE = "sensitive"

# Profile source types
SOURCE_OBSERVED = "observed"
SOURCE_TOLD = "told"
SOURCE_INFERRED = "inferred"

# Data directory
DATA_DIR = "ha_personal_assistant"
DB_FILENAME = "assistant.db"

# Agent pool config
AGENT_POOL_MAX_WORKERS = 3
AGENT_POOL_THREAD_PREFIX = "pa_agent"

# Confirmation timeout (seconds)
CONFIRMATION_TIMEOUT = 60

# RAG settings
RAG_TOP_K = 5
RAG_REINDEX_INTERVAL_HOURS = 24
RAG_HISTORY_REINDEX_INTERVAL_HOURS = 6

# Sync button entity
SYNC_BUTTON_ENTITY_ID = "button.ha_personal_assistant_sync_now"

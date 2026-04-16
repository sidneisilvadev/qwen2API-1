import os
import json
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Dict, Set

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding='utf-8',
        extra='ignore'
    )
    
    # Service Configuration
    VERSION: str = "2.2.1-safety"
    PORT: int = 7860
    WORKERS: int = 3
    ADMIN_KEY: str = "12a12b12c"
    REGISTER_SECRET: str = os.getenv("REGISTER_SECRET", "")
    SQLITE_DATA_DIR: str = str(DATA_DIR)

    # Engine Mode: httpx (fast direct), browser (fingerprinted, anti-ban) or hybrid
    ENGINE_MODE: str = os.getenv("ENGINE_MODE", "hybrid")
    NATIVE_TOOL_PASSTHROUGH: bool = os.getenv("NATIVE_TOOL_PASSTHROUGH", "true").lower() in ("1", "true", "yes", "on")
    # Browser Engine Configuration
    BROWSER_POOL_SIZE: int = int(os.getenv("BROWSER_POOL_SIZE", 2))
    MAX_INFLIGHT: int = 3
    DEFAULT_THINKING: bool = False
    DEFAULT_SEARCH: bool = False
    STREAM_KEEPALIVE_INTERVAL: int = int(os.getenv("STREAM_KEEPALIVE_INTERVAL", 5))

    # Retries and Rate Limiting
    MAX_RETRIES: int = 2
    TOOL_MAX_RETRIES: int = 2
    EMPTY_RESPONSE_RETRIES: int = 1
    CHAT_TIMEOUT: int = int(os.getenv("CHAT_TIMEOUT", 120))
    ACCOUNT_MIN_INTERVAL_MS: int = int(os.getenv("ACCOUNT_MIN_INTERVAL_MS", 300))
    REQUEST_JITTER_MIN_MS: int = int(os.getenv("REQUEST_JITTER_MIN_MS", 20))
    REQUEST_JITTER_MAX_MS: int = int(os.getenv("REQUEST_JITTER_MAX_MS", 80))
    RATE_LIMIT_BASE_COOLDOWN: int = int(os.getenv("RATE_LIMIT_BASE_COOLDOWN", 600))
    RATE_LIMIT_MAX_COOLDOWN: int = int(os.getenv("RATE_LIMIT_MAX_COOLDOWN", 3600))
    RATE_LIMIT_COOLDOWN: int = RATE_LIMIT_BASE_COOLDOWN


    # Data File Paths
    ACCOUNTS_FILE: str = os.getenv("ACCOUNTS_FILE", str(DATA_DIR / "accounts.json"))
    USERS_FILE: str = os.getenv("USERS_FILE", str(DATA_DIR / "users.json"))
    CAPTURES_FILE: str = os.getenv("CAPTURES_FILE", str(DATA_DIR / "captures.json"))
    CONFIG_FILE: str = os.getenv("CONFIG_FILE", str(DATA_DIR / "config.json"))



# Unified data storage is now in SQLite gateway.db

settings = Settings()

# Mapping of DB keys to Settings fields and their types
DB_MAPPING = {
    "engine_mode": ("ENGINE_MODE", "string"),
    "max_inflight": ("MAX_INFLIGHT", "int"),
    "browser_pool_size": ("BROWSER_POOL_SIZE", "int"),
    "default_thinking": ("DEFAULT_THINKING", "bool"),
    "default_search": ("DEFAULT_SEARCH", "bool"),
    "chat_timeout": ("CHAT_TIMEOUT", "int"),
    "account_min_interval_ms": ("ACCOUNT_MIN_INTERVAL_MS", "int"),
    "request_jitter_min_ms": ("REQUEST_JITTER_MIN_MS", "int"),
    "request_jitter_max_ms": ("REQUEST_JITTER_MAX_MS", "int"),
    "rate_limit_base_cooldown": ("RATE_LIMIT_BASE_COOLDOWN", "int"),
    "stream_keepalive_interval": ("STREAM_KEEPALIVE_INTERVAL", "int"),
}

async def load_db_overrides(db):
    """Load settings from SQLite and override the singleton instance."""
    import logging
    log = logging.getLogger("qwen2api.config")
    
    try:
        rows = await db.fetch_all("SELECT key, value, type FROM system_settings")
        overrides_count = 0
        for row in rows:
            db_key = row["key"]
            if db_key in DB_MAPPING:
                field_name, field_type = DB_MAPPING[db_key]
                val = await db.get_setting(db_key)
                setattr(settings, field_name, val)
                overrides_count += 1
        
        if overrides_count > 0:
            log.info(f"Loaded {overrides_count} configuration overrides from SQLite")
    except Exception as e:
        log.error(f"Failed to load DB settings overrides: {e}")

# Global model aliases
MODEL_MAP = {
    # Cloud Models (Mapped to Qwen equivalents)
    "gpt-4o":            "qwen-max",
    "gpt-4o-mini":       "qwen-plus",
    "gpt-4-turbo":       "qwen-max",
    "gpt-4":             "qwen-max",
    "gpt-3.5-turbo":     "qwen-plus",
    "claude-3-opus":             "qwen-max",
    "claude-3-5-sonnet":         "qwen-max",
    "claude-3-sonnet":           "qwen-plus",
    "claude-3-haiku":            "qwen-plus",
    "claude-3-5-haiku":          "qwen-plus",
    "llama-3.1-70b":             "qwen-max",
    "mixtral-8x7b":              "qwen-plus",
    "llama":                     "qwen-max",
    "claude":                    "qwen-max",
    
    # Qwen aliases
    "qwen":              "qwen-max-latest",
    "qwen-max":          "qwen-max-latest",
    "qwen-plus":         "qwen3.6-plus",
    "qwen-turbo":        "qwen3.5-flash",

    # Aggregator / Virtual Models
    "dual-sum":          "qwen-max",
}

# Default image generation model (uses actual base model from Qwen Web)
IMAGE_MODEL_DEFAULT = "qwen-max"

def resolve_model(name: str, discovered_models: list = None) -> str:
    """
    Resolve a model name to its target. 
    If it's a known real model (discovered), return it as is.
    Otherwise, check the alias map.
    """
    if discovered_models:
        for m in discovered_models:
            m_id = m.get("id", "")
            m_name = m.get("name", "")
            if name.lower() in (m_id.lower(), m_name.lower()):
                return m_id
                
    # Fallback to map
    mapped = MODEL_MAP.get(name, name)
    
    # Second pass: If mapped is still an alias but exists in discovered_models partially
    if discovered_models:
        for m in discovered_models:
            m_id = m.get("id", "")
            if mapped.lower() == m_id.lower():
                return m_id
            if mapped.split('-')[0] == m_id.split('-')[0] and 'max' in mapped and 'max' in m_id:
                 # fuzzy match for qwen-max
                 return m_id

    return mapped

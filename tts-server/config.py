"""Config loading for tts-server.

Uses pyyaml to load config.yaml and validates required keys.
"""

import os

import yaml

REQUIRED_KEYS = {
    "rumble.api_url": str,
    "rumble.api_key": str,
    "telegram.bot_token": str,
    "telegram.chat_id": str,
}

DEFAULT_CONFIG = {
    "rumble": {
        "poll_interval_seconds": 30,
    },
    "tts": {
        "voice": "en-US-AriaNeural",
        "rate": "+0%",
        "volume": "+0%",
    },
    "server": {
        "host": "0.0.0.0",
        "port": 8080,
        "spool_dir": "spool",
    },
    "telegram": {
        "bot_token": "",
        "chat_id": "",
    },
    # URL of the KITT bot's HTTP API for sending TTS audio to Telegram.
    # The KITT bot (kitt/telegram_bot.py) runs this server and exposes POST /send-audio.
    # tts-server POSTs MP3 here instead of calling Telegram directly — resolves the token conflict.
    "kitt_bot_url": "http://127.0.0.1:8082/send-audio",
    "events": {
        "new_follower": True,
        "new_subscriber": True,
        "gifted_sub": True,
        "live_on": True,
        "live_off": False,
        "chat_message": False,
        "rant": True,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override dict into base dict."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str | None = None) -> dict:
    """Load and validate YAML config from *path* (default: ``config.yaml``).

    Returns a dict with all required keys present. Raises ``KeyError`` if
    any required key is missing.
    """
    if path is None:
        path = "config.yaml"

    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError("Config file must contain a YAML mapping")

    config = _deep_merge(DEFAULT_CONFIG, raw)

    # Validate required keys by walking the dotted path
    for dotted_key, expected_type in REQUIRED_KEYS.items():
        parts = dotted_key.split(".")
        val = config
        for part in parts:
            if isinstance(val, dict):
                val = val.get(part)
                if val is None:
                    raise KeyError(f"Required config key '{dotted_key}' is missing")
            else:
                raise KeyError(f"Required config key '{dotted_key}' is missing")

        if not isinstance(val, expected_type):
            raise TypeError(
                f"Config key '{dotted_key}' must be of type {expected_type.__name__}, "
                f"got {type(val).__name__}"
            )

    return config
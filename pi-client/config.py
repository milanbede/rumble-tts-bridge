"""Config loading for pi-client.

Uses pyyaml to load config.yaml and validates required keys.
"""

import os

import yaml

REQUIRED_KEYS = {
    "tts_server.host": str,
}

DEFAULT_CONFIG = {
    "tts_server": {
        "port": 8080,
    },
    "player": {
        "poll_interval_seconds": 5,
        "volume": 90,
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


def build_server_url(cfg: dict) -> str:
    """Build the TTS server base URL from config dict."""
    host = cfg["tts_server"]["host"]
    port = cfg["tts_server"]["port"]
    return f"http://{host}:{port}"
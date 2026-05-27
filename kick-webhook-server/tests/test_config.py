"""Tests for config.load_config()."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from config import load_config


def test_load_config_returns_all_keys():
    """load_config() returns a dict with all required keys when config is valid."""
    config = {
        "kick": {"oauth_token": "tok", "client_id": "id", "client_secret": "sec",
                 "broadcaster_user_id": 1, "public_key_pem": "-----BEGIN PUBLIC KEY-----\nkey\n-----END PUBLIC KEY-----"},
        "server": {"host": "0.0.0.0", "port": 8081, "spool_dir": "../spool"},
        "tts": {"voice": "en-US-AriaNeural", "rate": "+0%", "volume": "+0%"},
        "events": {"channel.followed": True, "channel.subscription.new": True,
                   "channel.subscription.gifts": True, "channel.subscription.renewal": False,
                   "chat.message.sent": False},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        tmp_path = f.name
    try:
        result = load_config(tmp_path)
        assert "kick" in result
        assert "server" in result
        assert "tts" in result
        assert "events" in result
    finally:
        os.unlink(tmp_path)


def test_load_config_raises_keyerror_for_missing_section():
    """Missing required section raises KeyError with the key name."""
    config = {
        "kick": {},
        "server": {},
        # missing tts and events
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        tmp_path = f.name
    try:
        with pytest.raises(KeyError):
            load_config(tmp_path)
    finally:
        os.unlink(tmp_path)


def test_load_config_loads_from_file_path():
    """load_config() reads from the file path passed via --config argument."""
    config = {
        "kick": {"oauth_token": "tok", "client_id": "id", "client_secret": "sec",
                 "broadcaster_user_id": 1, "public_key_pem": "key"},
        "server": {"host": "0.0.0.0", "port": 8081, "spool_dir": "../spool"},
        "tts": {"voice": "en-US-AriaNeural", "rate": "+0%", "volume": "+0%"},
        "events": {"channel.followed": True, "channel.subscription.new": True,
                   "channel.subscription.gifts": True, "channel.subscription.renewal": False,
                   "chat.message.sent": False},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        tmp_path = f.name
    try:
        # Simulate --config argument being the file path
        result = load_config(tmp_path)
        assert isinstance(result, dict)
        assert result["server"]["port"] == 8081
    finally:
        os.unlink(tmp_path)
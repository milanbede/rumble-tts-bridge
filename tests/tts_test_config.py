"""Tests for tts-server config loading."""

import importlib.util
import os
import sys

import pytest

# Use importlib to load config.py from tts-server to avoid module name collisions
TTS_SERVER_DIR = os.path.join(os.path.dirname(__file__), "..", "tts-server")
_CONFIG_MODULE = None


def _load_config_module():
    global _CONFIG_MODULE
    if _CONFIG_MODULE is not None:
        return _CONFIG_MODULE
    spec = importlib.util.spec_from_file_location(
        "tts_config", os.path.join(TTS_SERVER_DIR, "config.py")
    )
    mod = importlib.util.module_from_spec(spec)
    # Ensure tts-server dir is in sys.path for any relative imports
    sys.path.insert(0, TTS_SERVER_DIR)
    spec.loader.exec_module(mod)
    _CONFIG_MODULE = mod
    return mod


def test_load_config_returns_dict(tmp_path):
    """Load a valid config and verify all required keys are present."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
rumble:
  api_url: "https://api.rumble.com/live_stream/v1.1/updates"
  api_key: "key123"
  poll_interval_seconds: 30
tts:
  voice: "en-US-AriaNeural"
  rate: "+0%"
  volume: "+0%"
server:
  host: "0.0.0.0"
  port: 8080
  spool_dir: "spool"
events:
  new_follower: true
  new_subscriber: true
  gifted_sub: true
  live_on: true
  live_off: false
  chat_message: false
  rant: true
"""
    )
    cfg = _load_config_module().load_config(str(cfg_file))
    assert isinstance(cfg, dict)
    assert cfg["rumble"]["api_key"] == "key123"
    assert cfg["server"]["port"] == 8080


def test_missing_required_key_raises(tmp_path):
    """A config missing a required key should raise KeyError."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
rumble:
  api_url: "https://api.rumble.com/live_stream/v1.1/updates"
  # missing api_key
"""
    )
    with pytest.raises(KeyError):
        _load_config_module().load_config(str(cfg_file))


def test_defaults_are_applied(tmp_path):
    """Keys not in config file should get default values."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
rumble:
  api_url: "https://api.rumble.com/live_stream/v1.1/updates"
  api_key: "key123"
"""
    )
    cfg = _load_config_module().load_config(str(cfg_file))
    assert cfg["server"]["port"] == 8080
    assert cfg["server"]["host"] == "0.0.0.0"
    assert cfg["tts"]["voice"] == "en-US-AriaNeural"
    assert cfg["events"]["new_follower"] is True
    assert cfg["events"]["live_off"] is False


def test_config_overrides_defaults(tmp_path):
    """User-provided values should override defaults."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
rumble:
  api_url: "https://api.rumble.com/live_stream/v1.1/updates"
  api_key: "key123"
  poll_interval_seconds: 60
server:
  port: 9090
"""
    )
    cfg = _load_config_module().load_config(str(cfg_file))
    assert cfg["rumble"]["poll_interval_seconds"] == 60
    assert cfg["server"]["port"] == 9090


def test_invalid_yml_raises(tmp_path):
    """Invalid YAML content should raise an exception."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(": invalid yaml [\n")
    with pytest.raises(Exception):
        _load_config_module().load_config(str(cfg_file))
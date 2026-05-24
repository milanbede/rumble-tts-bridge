"""Tests for pi-client config loading."""

import importlib.util
import os
import sys

import pytest

# Use importlib to load config.py from pi-client to avoid module name collisions
PI_CLIENT_DIR = os.path.join(os.path.dirname(__file__), "..", "pi-client")
_CONFIG_MODULE = None


def _load_config_module():
    global _CONFIG_MODULE
    if _CONFIG_MODULE is not None:
        return _CONFIG_MODULE
    spec = importlib.util.spec_from_file_location(
        "pi_config", os.path.join(PI_CLIENT_DIR, "config.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, PI_CLIENT_DIR)
    spec.loader.exec_module(mod)
    _CONFIG_MODULE = mod
    return mod


def test_load_config_returns_dict(tmp_path):
    """Load a valid config and verify required keys."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
tts_server:
  host: "192.168.1.100"
  port: 8080
player:
  poll_interval_seconds: 5
  volume: 90
"""
    )
    mod = _load_config_module()
    cfg = mod.load_config(str(cfg_file))
    assert cfg["tts_server"]["host"] == "192.168.1.100"
    assert cfg["player"]["volume"] == 90


def test_build_server_url(tmp_path):
    """build_server_url() constructs http://host:port from config."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
tts_server:
  host: "192.168.1.100"
  port: 8080
"""
    )
    mod = _load_config_module()
    cfg = mod.load_config(str(cfg_file))
    url = mod.build_server_url(cfg)
    assert url == "http://192.168.1.100:8080"


def test_missing_host_raises(tmp_path):
    """Config missing tts_server.host should raise KeyError."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
tts_server:
  port: 8080
"""
    )
    with pytest.raises(KeyError):
        _load_config_module().load_config(str(cfg_file))


def test_missing_port_defaults(tmp_path):
    """Config missing tts_server.port should default to 8080."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
tts_server:
  host: "192.168.1.100"
"""
    )
    mod = _load_config_module()
    cfg = mod.load_config(str(cfg_file))
    assert cfg["tts_server"]["port"] == 8080


def test_defaults_are_applied(tmp_path):
    """Optional keys should get default values."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
tts_server:
  host: "192.168.1.100"
  port: 8080
"""
    )
    mod = _load_config_module()
    cfg = mod.load_config(str(cfg_file))
    assert cfg["player"]["poll_interval_seconds"] == 5
    assert cfg["player"]["volume"] == 90


def test_config_overrides_defaults(tmp_path):
    """User-provided values override defaults."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
tts_server:
  host: "10.0.0.50"
  port: 9090
player:
  poll_interval_seconds: 10
  volume: 75
"""
    )
    mod = _load_config_module()
    cfg = mod.load_config(str(cfg_file))
    assert cfg["tts_server"]["port"] == 9090
    assert cfg["player"]["volume"] == 75
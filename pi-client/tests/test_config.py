"""Tests for config loading — R1 spec exactly."""

import pytest
import yaml
from pathlib import Path
from config import load_config, build_server_url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_config_file(tmp_path):
    """Return a factory that writes a config dict to a temp YAML file."""
    def _write(config_dict):
        p = tmp_path / "config.yaml"
        p.write_text(yaml.safe_dump(config_dict))
        return str(p)
    return _write


# ---------------------------------------------------------------------------
# R1: load_config — 4 required fields
# ---------------------------------------------------------------------------

def test_load_config_returns_dict(temp_config_file):
    cfg = load_config(temp_config_file({"tts_server": {"host": "127.0.0.1"}}))
    assert isinstance(cfg, dict)


def test_load_config_host(temp_config_file):
    cfg = load_config(temp_config_file({
        "tts_server": {"host": "192.168.1.100", "port": 8080},
        "player": {"poll_interval_seconds": 5, "volume": 90},
    }))
    assert cfg["tts_server"]["host"] == "192.168.1.100"


def test_load_config_port(temp_config_file):
    cfg = load_config(temp_config_file({
        "tts_server": {"host": "localhost", "port": 9000},
        "player": {"poll_interval_seconds": 3, "volume": 50},
    }))
    assert cfg["tts_server"]["port"] == 9000


def test_load_config_volume(temp_config_file):
    cfg = load_config(temp_config_file({
        "tts_server": {"host": "localhost", "port": 8080},
        "player": {"poll_interval_seconds": 5, "volume": 75},
    }))
    assert cfg["player"]["volume"] == 75


def test_load_config_poll_interval(temp_config_file):
    cfg = load_config(temp_config_file({
        "tts_server": {"host": "localhost", "port": 8080},
        "player": {"poll_interval_seconds": 10, "volume": 90},
    }))
    assert cfg["player"]["poll_interval_seconds"] == 10


# ---------------------------------------------------------------------------
# build_server_url
# ---------------------------------------------------------------------------

def test_build_server_url(temp_config_file):
    cfg = load_config(temp_config_file({
        "tts_server": {"host": "192.168.1.100", "port": 8080},
        "player": {"poll_interval_seconds": 5, "volume": 90},
    }))
    assert build_server_url(cfg) == "http://192.168.1.100:8080"


# ---------------------------------------------------------------------------
# Defaults when optional keys are omitted
# ---------------------------------------------------------------------------

def test_defaults_applied_when_optional_keys_missing(temp_config_file):
    cfg = load_config(temp_config_file({
        "tts_server": {"host": "localhost"},
    }))
    assert cfg["tts_server"]["host"] == "localhost"
    assert cfg["tts_server"]["port"] == 8080
    assert cfg["player"]["poll_interval_seconds"] == 5
    assert cfg["player"]["volume"] == 90


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

def test_missing_host_raises_keyerror(temp_config_file):
    with pytest.raises(KeyError):
        load_config(temp_config_file({"tts_server": {"port": 8080}}))


def test_missing_config_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "nonexistent.yaml"))

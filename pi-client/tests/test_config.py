"""Tests for pi-client config loading (spec R1)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Dynamically load config.py from pi-client/
PI_CLIENT_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, PI_CLIENT_DIR)

from config import build_server_url, load_config


# ── helpers ──────────────────────────────────────────────────────────────────


# ── R1 spec cases ──────────────────────────────────────────────────────────

def test_load_config_returns_tts_server_host(tmp_path):
    """R1: tts_server.host is loaded."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "tts_server:\n  host: '192.168.1.100'\n  port: 8080\n"
        "player:\n  volume: 90\n  poll_interval_seconds: 5\n"
    )
    cfg = load_config(str(cfg_file))
    assert cfg["tts_server"]["host"] == "192.168.1.100"


def test_load_config_returns_player_volume_int(tmp_path):
    """R1: player.volume is returned as an int 0–100."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "tts_server:\n  host: '192.168.1.100'\n  port: 8080\n"
        "player:\n  volume: 75\n  poll_interval_seconds: 5\n"
    )
    cfg = load_config(str(cfg_file))
    assert isinstance(cfg["player"]["volume"], int)
    assert 0 <= cfg["player"]["volume"] <= 100


def test_load_config_returns_poll_interval_seconds(tmp_path):
    """R1: player.poll_interval_seconds is returned as an int."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "tts_server:\n  host: '192.168.1.100'\n  port: 8080\n"
        "player:\n  poll_interval_seconds: 10\n  volume: 90\n"
    )
    cfg = load_config(str(cfg_file))
    assert isinstance(cfg["player"]["poll_interval_seconds"], int)


def test_build_server_url_combine_host_and_port(tmp_path):
    """R1: tts_server.host + tts_server.port → http://host:port."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "tts_server:\n  host: '192.168.1.100'\n  port: 8080\n"
        "player:\n  volume: 90\n  poll_interval_seconds: 5\n"
    )
    cfg = load_config(str(cfg_file))
    url = build_server_url(cfg)
    assert url == "http://192.168.1.100:8080"

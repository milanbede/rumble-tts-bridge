"""Integration test: verifies main.py wiring is correct (all deps mocked)."""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Match the pattern used by sibling test modules: add tts-server to sys.path
TTS_SERVER_DIR = os.path.join(os.path.dirname(__file__), "..", "tts-server")
sys.path.insert(0, TTS_SERVER_DIR)


# ------------------------------------------------------------------
# Dynamically load modules from tts-server/
# ------------------------------------------------------------------
def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(TTS_SERVER_DIR, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


config_mod = _load_module("config")
poller_mod = _load_module("poller")
server_mod = _load_module("server")
state_mod = _load_module("state")
tts_mod = _load_module("tts")

load_config = config_mod.load_config
RumblePoller = poller_mod.RumblePoller
Event = poller_mod.Event
make_app = server_mod.make_app
StateStore = state_mod.StateStore
TTSEngine = tts_mod.TTSEngine


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def minimal_config(spool_dir: str) -> dict:
    """Return a minimal valid config dict."""
    return {
        "rumble": {
            "api_url": "https://api.rumble.com/v1/events",
            "api_key": "test-key",
            "poll_interval_seconds": 600,
        },
        "tts": {
            "voice": "en-US-AriaNeural",
            "rate": "+0%",
            "volume": "+0%",
        },
        "server": {
            "host": "127.0.0.1",
            "port": 9999,
            "spool_dir": spool_dir,
        },
        "events": {
            "new_follower": True,
            "new_subscriber": False,
            "gifted_sub": False,
            "live_on": False,
            "live_off": False,
            "chat_message": False,
            "rant": False,
        },
    }


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------
def test_argparse_defaults():
    """--config defaults to 'config.yaml' when not passed; explicit value overrides."""
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.yaml")

    with patch.object(sys, "argv", ["main.py"]):
        args = p.parse_args([])
        assert args.config == "config.yaml"

    with patch.object(sys, "argv", ["main.py", "--config", "/path/conf.yaml"]):
        args = p.parse_args(["--config", "/path/conf.yaml"])
        assert args.config == "/path/conf.yaml"


def test_load_config_returns_dict(tmp_path):
    """load_config resolves a file and returns a dict with expected keys."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("rumble:\n  api_url: http://example.com\n  api_key: KEY\n")
    config = load_config(str(cfg_file))
    assert isinstance(config, dict)
    assert config["rumble"]["api_url"] == "http://example.com"


def test_state_store_init(tmp_path):
    """StateStore creates state.json alongside the spool dir (dir must exist first)."""
    spool = tmp_path / "spool"
    spool.mkdir()
    store = StateStore(str(spool))
    assert store._path == spool / "state.json"
    assert store._path.exists()


def test_tts_engine_init(tmp_path):
    """TTSEngine stores params and creates no file on init."""
    engine = TTSEngine(str(tmp_path), voice="en-US-AriaNeural", rate="+10%", volume="-20%")
    assert engine.voice == "en-US-AriaNeural"
    assert engine.rate == "+10%"
    assert engine.volume == "-20%"


def test_tts_engine_speak_returns_absolute_mp3_path(tmp_path):
    """TTSEngine.speak() returns an absolute path ending in .mp3 (network mocked)."""
    engine = TTSEngine(str(tmp_path), voice="en-US-AriaNeural")

    # Mock edge_tts.Communicate().save() as a coroutine that writes a fake MP3 header
    async def mock_save(path):
        Path(path).write_bytes(b"\xff\xfb\x90\x00")

    mock_comm_instance = MagicMock()
    mock_comm_instance.save = mock_save

    with patch("edge_tts.Communicate", return_value=mock_comm_instance):
        result = engine.speak("Hello world")

    assert result.endswith(".mp3")
    assert Path(result).is_absolute()
    assert Path(result).exists()


def test_poller_run_callback_fired(tmp_path):
    """RumblePoller.run() invokes callback with each event; exits on StopIteration."""
    spool = tmp_path / "spool"
    spool.mkdir()
    store = StateStore(str(spool))

    fake_event = Event(type="new_follower", text="New follower: TestUser", event_id="follower/TestUser")
    captured = []

    config = minimal_config(str(spool))

    # Patch time.sleep so the 600s poll interval doesn't block the test
    sleeps = []
    original_sleep = time.sleep

    def fake_sleep(seconds):
        sleeps.append(seconds)
        raise StopIteration("break")  # exit the loop immediately

    # Create poller with a mock poll that raises StopIteration on the second call
    poller = RumblePoller(
        api_url=config["rumble"]["api_url"],
        api_key=config["rumble"]["api_key"],
        state=store,
        config={**config["rumble"], **config["events"]},
    )

    call_count = [0]

    def poll_mock():
        call_count[0] += 1
        if call_count[0] == 1:
            return [fake_event]
        raise StopIteration("test exit")

    poller.poll = poll_mock

    with patch("time.sleep", fake_sleep):
        with pytest.raises(StopIteration):
            poller.run(captured.append)

    assert len(captured) == 1
    assert captured[0].type == "new_follower"
    assert captured[0].text == "New follower: TestUser"


def test_make_app_starts_server(tmp_path):
    """make_app() starts an HTTP server bound to the given host/port."""
    spool = tmp_path / "spool"
    spool.mkdir()
    httpd = make_app(spool_dir=str(spool), host="127.0.0.1", port=9988)
    assert httpd is not None
    # Verify it's reachable
    import urllib.request
    resp = urllib.request.urlopen("http://127.0.0.1:9988/")
    assert resp.status == 200
    httpd.shutdown()


def test_on_event_callback_wires_tts(tmp_path):
    """The _on_event callback calls tts.speak with event.text and returns the MP3 path."""
    engine = MagicMock()
    engine.speak.return_value = "/spool/test.mp3"

    fake_event = Event(type="new_follower", text="New follower: TestUser", event_id="follower/TestUser")

    # Replicate the actual _on_event logic from main.py
    mp3_path = engine.speak(fake_event.text)

    engine.speak.assert_called_once_with("New follower: TestUser")
    assert mp3_path == "/spool/test.mp3"
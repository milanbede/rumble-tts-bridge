"""Integration test: verify main.py wires all components correctly."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from main import _on_event, main
from poller import Event


# ── helpers ──────────────────────────────────────────────────────────────────

def minimal_config(tmpdir: Path) -> dict:
    spool = str(tmpdir / "spool")
    os.makedirs(spool)
    return {
        "rumble": {
            "api_url": "https://api.rumble.com/live_stream/v1.1/updates",
            "api_key": "test-key-0001",
            "poll_interval_seconds": 30,
        },
        "tts": {
            "voice": "en-US-AriaNeural",
            "rate": "+0%",
            "volume": "+0%",
        },
        "server": {
            "host": "127.0.0.1",
            "port": 19999,
            "spool_dir": spool,
        },
        "telegram": {
            "bot_token": "test-bot-token",
            "chat_id": "123456789",
        },
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


# ── test _on_event callback ──────────────────────────────────────────────────

def test_on_event_logs_event_and_speaks(monkeypatch, tmp_path):
    fake_tts = MagicMock()
    fake_tts.speak.return_value = str(tmp_path / "output.mp3")

    # Capture log output
    logged = []
    monkeypatch.setattr("main.log", MagicMock(info=lambda msg, *args: logged.append(msg % args)))

    ev = Event(type="new_follower", text="New follower: Alice", event_id="follower/Alice")
    _on_event(fake_tts, ev)

    fake_tts.speak.assert_called_once_with("New follower: Alice")
    assert any("Event received" in msg for msg in logged)
    assert any("MP3 written" in msg for msg in logged)


# ── test main() wiring (no network, no real TTS) ────────────────────────────

def test_main_wires_all_components(monkeypatch, tmp_path):
    cfg = minimal_config(tmp_path)

    # Mock load_config to return our controlled config
    mock_load_config = MagicMock(return_value=cfg)
    monkeypatch.setattr("main.load_config", mock_load_config)

    # Mock StateStore — no actual JSON persistence needed
    mock_state_instance = MagicMock()
    mock_state_instance.seen.return_value = False
    monkeypatch.setattr("main.StateStore", MagicMock(return_value=mock_state_instance))

    # Mock TTSEngine so speak() returns a fake path (no network)
    mock_tts_instance = MagicMock()
    mock_tts_instance.speak.return_value = str(tmp_path / "fake.mp3")
    monkeypatch.setattr("main.TTSEngine", MagicMock(return_value=mock_tts_instance))

    # Mock RumblePoller — capture the callback passed to run()
    captured_callback = None

    def capture_run(callback):
        nonlocal captured_callback
        captured_callback = callback

    mock_poller_class = MagicMock()
    mock_poller_instance = MagicMock()
    mock_poller_class.return_value = mock_poller_instance
    mock_poller_instance.run.side_effect = capture_run
    monkeypatch.setattr("main.RumblePoller", mock_poller_class)

    # Mock make_app — track it was called with correct args
    app_calls = []
    def mock_make_app(spool_dir, host, port, tts_engine=None, telegram_conf=None):
        app_calls.append((spool_dir, host, port, tts_engine, telegram_conf))
        return MagicMock()  # httpd replacement
    monkeypatch.setattr("main.make_app", mock_make_app)

    # Patch sys.argv so argparse doesn't get real CLI args
    monkeypatch.setattr("sys.argv", ["tts-server", "--config", str(tmp_path / "config.yaml")])

    # Run main() — poller.run() is mocked so it returns immediately
    try:
        main()
    except SystemExit:
        pass

    # Verify all components were created and wired
    mock_load_config.assert_called_once()

    mock_poller_class.assert_called_once()
    call_kwargs = mock_poller_class.call_args.kwargs
    assert call_kwargs["api_url"] == cfg["rumble"]["api_url"]
    assert call_kwargs["api_key"] == cfg["rumble"]["api_key"]
    assert call_kwargs["state"] is mock_state_instance

    assert len(app_calls) == 1
    spool, host, port, tts_eng, tg_conf = app_calls[0]
    assert spool == cfg["server"]["spool_dir"]
    assert host == cfg["server"]["host"]
    assert port == cfg["server"]["port"]
    assert tts_eng is mock_tts_instance
    assert tg_conf == {"bot_token": "test-bot-token", "chat_id": "123456789"}

    # Verify callback fires TTS correctly
    assert captured_callback is not None
    ev = Event(type="new_follower", text="Test event", event_id="follower/Test")
    captured_callback(ev)
    mock_tts_instance.speak.assert_called_once_with("Test event")
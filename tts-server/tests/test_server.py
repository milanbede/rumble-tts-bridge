"""Tests for server.py — GET /, GET /<file>.mp3, POST /ack, POST /announce."""

import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path
from threading import Thread
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server import _make_handler, _create_httpd


# ── helpers ──────────────────────────────────────────────────────────────────

class _CapturingHandler:
    """Launch a real HTTP server on a random port, yield its URL, then shut down."""

    def __init__(self, handler_class):
        self.handler_class = handler_class
        self.httpd = None
        self.thread = None
        self.base_url = None

    def __enter__(self):
        self.httpd = _create_httpd("127.0.0.1", 0, self.handler_class)
        self.port = self.httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.httpd.shutdown()
        self.thread.join(timeout=5)


def _post(url, body, content_type="application/json"):
    req = urllib.request.Request(url, data=body, headers={"Content-Type": content_type})
    with urllib.request.urlopen(req) as resp:
        return resp


def _get(url, path):
    req = urllib.request.Request(f"{url}{path}")
    with urllib.request.urlopen(req) as resp:
        return resp


# ── /announce tests ──────────────────────────────────────────────────────────

def test_announce_missing_body():
    """POST /announce with no body returns 400."""
    fake_tts = MagicMock()
    fake_tts.speak.return_value = "/tmp/fake.mp3"

    Handler = _make_handler("/tmp/fake_spool", fake_tts, {"bot_token": "x", "chat_id": "y"})
    with _CapturingHandler(Handler) as srv:
        req = urllib.request.Request(srv.base_url + "/announce", data=b"", headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            resp = e
        else:
            raise AssertionError("Expected HTTPError")

    assert resp.code == 400
    assert b"Missing request body" in resp.read()


def test_announce_missing_text():
    """POST /announce with empty text field returns 400."""
    fake_tts = MagicMock()
    fake_tts.speak.return_value = "/tmp/fake.mp3"

    Handler = _make_handler("/tmp/fake_spool", fake_tts, {"bot_token": "x", "chat_id": "y"})
    with _CapturingHandler(Handler) as srv:
        body = json.dumps({"event_type": "follow", "text": ""}).encode()
        req = urllib.request.Request(srv.base_url + "/announce", data=body, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            resp = e
        else:
            raise AssertionError("Expected HTTPError")

    assert resp.code == 400
    assert b"Missing 'text' field" in resp.read()


def test_announce_invalid_json():
    """POST /announce with invalid JSON returns 400."""
    fake_tts = MagicMock()
    fake_tts.speak.return_value = "/tmp/fake.mp3"

    Handler = _make_handler("/tmp/fake_spool", fake_tts, {"bot_token": "x", "chat_id": "y"})
    with _CapturingHandler(Handler) as srv:
        req = urllib.request.Request(srv.base_url + "/announce", data=b"not json{", headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            resp = e
        else:
            raise AssertionError("Expected HTTPError")

    assert resp.code == 400
    assert b"Invalid JSON" in resp.read()


def test_announce_tts_failure():
    """TTS failure returns 500 with error message."""
    fake_tts = MagicMock()
    fake_tts.speak.side_effect = Exception("TTS network timeout")
    fake_tts.voice = "en-US-AriaNeural"

    Handler = _make_handler("/tmp/fake_spool", fake_tts, {"bot_token": "x", "chat_id": "y"})
    with _CapturingHandler(Handler) as srv:
        body = json.dumps({"event_type": "follow", "text": "Hello"}).encode()
        req = urllib.request.Request(srv.base_url + "/announce", data=body, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            resp = e
        else:
            raise AssertionError("Expected HTTPError")

    assert resp.code == 500
    data = json.loads(resp.read())
    assert "TTS generation failed" in data["error"]


def test_announce_happy_path():
    """POST /announce with valid payload returns 200 and sends Telegram messages."""
    fake_tts = MagicMock()
    fake_tts.voice = "en-US-AriaNeural"

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        fake_mp3_path = f.name

    try:
        fake_tts.speak.return_value = fake_mp3_path

        Handler = _make_handler("/tmp/fake_spool", fake_tts, {"bot_token": "bot123", "chat_id": "chat456"})
        with _CapturingHandler(Handler) as srv:
            with patch("server.urllib.request.urlopen", MagicMock()) as mock_urlopen:
                mock_ctx = MagicMock()
                mock_ctx.__enter__ = MagicMock(return_value=MagicMock(status=200))
                mock_ctx.__exit__ = MagicMock(return_value=False)
                mock_urlopen.return_value = mock_ctx

                body = json.dumps({
                    "event_type": "subscription",
                    "text": "New subscriber Alice!",
                    "tts_voice": "en-US-JennyNeural",
                }).encode()
                req = urllib.request.Request(srv.base_url + "/announce", data=body, headers={"Content-Type": "application/json"})
                resp = urllib.request.urlopen(req)

        assert resp.code == 200
        data = json.loads(resp.read())
        assert data == {"ok": True}

        # Verify TTS spoke with correct text
        fake_tts.speak.assert_called_once()
        call_args = fake_tts.speak.call_args
        assert call_args[0][0] == "New subscriber Alice!"
        assert call_args[1]["job_id"].startswith("announce_subscription_")

        # Verify voice was temporarily overridden then restored
        assert fake_tts.voice == "en-US-AriaNeural"

    finally:
        if os.path.exists(fake_mp3_path):
            os.unlink(fake_mp3_path)


def test_announce_cleans_up_mp3_on_telegram_error():
    """If Telegram sendMessage fails, the MP3 is still cleaned up."""
    fake_tts = MagicMock()
    fake_tts.voice = "en-US-AriaNeural"

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        fake_mp3_path = f.name

    try:
        fake_tts.speak.return_value = fake_mp3_path
        Path(fake_mp3_path).write_bytes(b"fake mp3 data")
        assert os.path.exists(fake_mp3_path)

        Handler = _make_handler("/tmp/fake_spool", fake_tts, {"bot_token": "x", "chat_id": "y"})
        with _CapturingHandler(Handler) as srv:
            with patch("server.urllib.request.urlopen", MagicMock()) as mock_urlopen:
                mock_ctx = MagicMock()
                mock_ctx.__enter__ = MagicMock(return_value=MagicMock(status=500))
                mock_ctx.__exit__ = MagicMock(return_value=False)
                mock_urlopen.return_value = mock_ctx

                body = json.dumps({"event_type": "follow", "text": "Hello"}).encode()
                req = urllib.request.Request(srv.base_url + "/announce", data=body, headers={"Content-Type": "application/json"})
                try:
                    urllib.request.urlopen(req)
                except urllib.error.HTTPError as e:
                    resp = e
                else:
                    raise AssertionError("Expected HTTPError")

        assert resp.code == 500
        # MP3 should have been deleted even though Telegram failed
        assert not os.path.exists(fake_mp3_path), "MP3 should be cleaned up after Telegram failure"
    finally:
        if os.path.exists(fake_mp3_path):
            os.unlink(fake_mp3_path)
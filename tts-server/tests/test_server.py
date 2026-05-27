"""Tests for server.py — GET /, GET /<file>.mp3, POST /ack, POST /announce."""

import io
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path
from threading import Thread
from typing import Any
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

    Handler = _make_handler("/tmp/fake_spool", fake_tts, {"bot_token": "x", "chat_id": "y"},
                            kitt_bot_url="http://127.0.0.1:8082/send-audio")
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

    Handler = _make_handler("/tmp/fake_spool", fake_tts, {"bot_token": "x", "chat_id": "y"},
                            kitt_bot_url="http://127.0.0.1:8082/send-audio")
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

    Handler = _make_handler("/tmp/fake_spool", fake_tts, {"bot_token": "x", "chat_id": "y"},
                            kitt_bot_url="http://127.0.0.1:8082/send-audio")
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

    Handler = _make_handler("/tmp/fake_spool", fake_tts, {"bot_token": "x", "chat_id": "y"},
                            kitt_bot_url="http://127.0.0.1:8082/send-audio")
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


def _make_handler_instance(spool_dir, fake_tts, telegram_conf, kitt_bot_url="http://127.0.0.1:8082"):
    """Create a handler class and instantiate it with mocked HTTP request internals."""
    Handler = _make_handler(spool_dir, fake_tts, telegram_conf, kitt_bot_url=kitt_bot_url)
    h = Handler(MagicMock(), ("127.0.0.1", 9999), MagicMock())
    # Mock out BaseHTTPRequestHandler methods that _send_json depends on
    h.send_response = MagicMock()
    h.send_header = MagicMock()
    h.end_headers = MagicMock()
    h.wfile = MagicMock()
    return h


def test_announce_happy_path():
    """POST /announce generates KITT-prefixed TTS and POSTs it to the KITT bot."""
    fake_tts = MagicMock()
    fake_tts.voice = "en-US-AriaNeural"
    fake_tts.speak.return_value = "/tmp/fake.mp3"

    # Mock response from the KITT bot /send-audio endpoint
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)

    Handler = _make_handler(
        "/tmp/fake_spool", fake_tts,
        {"bot_token": "bot123", "chat_id": "chat456"},
        kitt_bot_url="http://127.0.0.1:8082/send-audio",
    )
    with _CapturingHandler(Handler) as srv:
        with patch("server.urllib.request.urlopen", return_value=mock_response):
            body = json.dumps({
                "event_type": "subscription",
                "text": "New subscriber Alice!",
                "tts_voice": "en-US-JennyNeural",
            }).encode()
            req = urllib.request.Request(
                srv.base_url + "/announce",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req)

    assert resp.status == 200

    # Verify TTS received KITT-prefixed text
    fake_tts.speak.assert_called_once()
    call_args = fake_tts.speak.call_args
    assert call_args[0][0] == "KITT here. New subscriber Alice!"
    assert call_args[1]["job_id"].startswith("announce_subscription_")

    # Verify voice override was applied then restored
    assert fake_tts.voice == "en-US-AriaNeural"


def test_announce_cleans_up_mp3_on_kitt_bot_error():
    """If the KITT bot returns an error, the MP3 is still cleaned up."""
    fake_tts = MagicMock()
    fake_tts.voice = "en-US-AriaNeural"

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        fake_mp3_path = f.name

    try:
        fake_tts.speak.return_value = fake_mp3_path
        Path(fake_mp3_path).write_bytes(b"fake mp3 data")
        assert os.path.exists(fake_mp3_path)

        Handler = _make_handler(
            "/tmp/fake_spool", fake_tts,
            {"bot_token": "x", "chat_id": "y"},
            kitt_bot_url="http://127.0.0.1:8082/send-audio",
        )
        with _CapturingHandler(Handler) as srv:
            # Make urlopen raise HTTPError so the server catches it as a dispatch failure
            err = urllib.error.HTTPError(
                srv.base_url, 500, "KITT bot error", {}, None
            )
            with patch("server.urllib.request.urlopen", side_effect=err):
                body = json.dumps({"event_type": "follow", "text": "Hello"}).encode()
                req = urllib.request.Request(
                    srv.base_url + "/announce",
                    data=body,
                    headers={"Content-Type": "application/json"},
                )
                try:
                    urllib.request.urlopen(req)
                except urllib.error.HTTPError:
                    pass  # expected

        # MP3 should have been deleted even though the KITT bot returned an error
        assert not os.path.exists(fake_mp3_path), \
            "MP3 should be cleaned up after KITT bot failure"
    finally:
        if os.path.exists(fake_mp3_path):
            os.unlink(fake_mp3_path)

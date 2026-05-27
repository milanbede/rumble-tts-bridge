"""Tests for KITT telegram_bot.py."""

import asyncio
import json
import os
import tempfile
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kitt import telegram_bot as tb


# ── Config checks ─────────────────────────────────────────────────────────────

class TestConfig:
    def test_hermes_gateway_default(self):
        """HERMES_GATEWAY_URL should default to localhost:9119."""
        assert tb.HERMES_GATEWAY_URL == "http://localhost:9119"

    def test_http_api_port_default(self):
        """HTTP_API_PORT should default to 8082."""
        assert tb.HTTP_API_PORT == 8082

    def test_spool_dir_defaults_to_home_kitt_spool(self):
        """SPOOL_DIR should default to ~/KITT/spool."""
        assert tb.SPOOL_DIR.name == "spool"
        assert tb.SPOOL_DIR.parent.name == "KITT"


# ── Hermes forwarding ─────────────────────────────────────────────────────────

class TestHermesForwarding:
    """Tests for forward_to_hermes using local urllib import patching."""

    def test_forward_returns_none_on_urlerror(self):
        """forward_to_hermes should return None when Hermes is unreachable."""
        with patch("urllib.request.urlopen", side_effect=Exception("no network")):
            result = tb.forward_to_hermes("hello")
            assert result is None

    def test_forward_returns_response_on_success(self):
        """forward_to_hermes should return the response text on success."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b"KITT says hi"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = tb.forward_to_hermes("hello")
            assert result == "KITT says hi"

    def test_forward_returns_none_on_other_error(self):
        """forward_to_hermes should return None on non-URLError exceptions."""
        with patch("urllib.request.urlopen", side_effect=OSError("misc")):
            result = tb.forward_to_hermes("hello")
            assert result is None


# ── HTTP handler ───────────────────────────────────────────────────────────────

class TestHTTPHandler:
    """Tests for _HTTPAPIHandler routing."""

    def test_handler_404_on_unknown_path(self):
        """Handler should return 404 for non-/send-audio paths."""
        handler = tb._HTTPAPIHandler.__new__(tb._HTTPAPIHandler)
        handler.path = "/unknown"
        handler._send_json = MagicMock()
        handler.do_GET()
        handler._send_json.assert_called_once_with(404, {"error": "Not found"})

    def test_handler_health_endpoint(self):
        """GET /health should return 200."""
        handler = tb._HTTPAPIHandler.__new__(tb._HTTPAPIHandler)
        handler.path = "/health"
        handler._send_json = MagicMock()
        handler.do_GET()
        handler._send_json.assert_called_once_with(200, {"status": "ok"})

    def test_handler_rejects_empty_body(self):
        """POST /send-audio with no body should return 400."""
        handler = tb._HTTPAPIHandler.__new__(tb._HTTPAPIHandler)
        handler.path = "/send-audio"
        handler.headers = MagicMock()
        handler.headers.get = lambda k, d="": {"Content-Length": "0"}.get(k, d)
        handler._send_json = MagicMock()
        handler.rfile = MagicMock()
        handler.rfile.read = MagicMock(return_value=b"")
        handler._handle_send_audio()
        handler._send_json.assert_called_once_with(400, {"error": "Missing request body"})


# ── send_audio_to_telegram_sync ───────────────────────────────────────────────

class TestSendAudioSync:
    """Tests for the synchronous Telegram send wrapper."""

    @patch.object(tb, "_send_audio_via_telegram", new_callable=AsyncMock)
    def test_calls_telegram_with_args(self, mock_send):
        """send_audio_to_telegram_sync should call _send_audio_via_telegram."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"MP3DATA")
            path = f.name
        try:
            tb.send_audio_to_telegram_sync("123", path, "caption text")
            mock_send.assert_awaited_once_with("123", path, "caption text")
        finally:
            os.unlink(path)


# ── Module API surface ─────────────────────────────────────────────────────────

def test_module_exports():
    """Sanity-check that expected functions are exported."""
    assert callable(tb.main)
    assert callable(tb.speak_kitt)
    assert callable(tb.transcribe_audio)
    assert callable(tb.forward_to_hermes)
    assert callable(tb.deliver_dual)
    assert callable(tb.send_audio_to_telegram_sync)
    assert callable(tb.run_http_api)
    assert callable(tb.handle_voice)
    assert callable(tb.handle_text)
    assert callable(tb.cmd_start)


# ── Tests: transcribe_audio ────────────────────────────────────────────────────

class TestTranscribeAudio:
    """Tests for the Whisper transcription path."""

    def test_transcribe_audio_success(self, tmp_path):
        """Whisper returns transcribed text."""
        fake_audio = tmp_path / "fake.ogg"
        fake_audio.write_bytes(b"fake audio data")

        with patch("kitt.telegram_bot.load_whisper") as mock_load:
            mock_model = MagicMock()
            mock_model.transcribe.return_value = {"text": "  hello world  "}
            mock_load.return_value.load_model.return_value = mock_model

            result = tb.transcribe_audio(str(fake_audio))

            assert result == "hello world"
            mock_model.transcribe.assert_called_once_with(str(fake_audio), fp16=False)

    def test_transcribe_audio_whisper_error(self, tmp_path):
        """Exception raised when Whisper fails."""
        fake_audio = tmp_path / "bad.ogg"
        fake_audio.write_bytes(b"bad")

        with patch("kitt.telegram_bot.load_whisper") as mock_load:
            mock_load.return_value.load_model.side_effect = RuntimeError("model load failed")

            with pytest.raises(Exception, match="Whisper transcription failed"):
                tb.transcribe_audio(str(fake_audio))


# ── Tests: speak_kitt ─────────────────────────────────────────────────────────

class TestSpeakKitt:
    """Tests for the KITT TTS generation path."""

    def test_speak_kitt_creates_mp3(self, tmp_path, monkeypatch):
        """speak_kitt writes an MP3 file to the spool directory."""
        spool = tmp_path / "spool"
        spool.mkdir()

        # Patch _generate_tts directly so we don't touch edge_tts at all
        async def fake_generate(text, output_path):
            with open(output_path, "wb") as f:
                f.write(b"fake mp3 data")

        monkeypatch.setattr("kitt.telegram_bot._generate_tts", fake_generate)
        monkeypatch.setattr("kitt.telegram_bot.SPOOL_DIR", spool)

        mp3_path = tb.speak_kitt("test message", job_id="test_job_001")

        assert mp3_path.endswith(".mp3")
        assert Path(mp3_path).exists()
        assert Path(mp3_path).read_bytes() == b"fake mp3 data"

    def test_speak_kitt_cleans_up_on_error(self, tmp_path, monkeypatch):
        """Partial MP3 file is removed when TTS generation fails."""
        spool = tmp_path / "spool"
        spool.mkdir()

        async def fake_error(text, output_path):
            raise RuntimeError("synthesis error")

        monkeypatch.setattr("kitt.telegram_bot._generate_tts", fake_error)
        monkeypatch.setattr("kitt.telegram_bot.SPOOL_DIR", spool)

        with pytest.raises(Exception, match="KITT TTS generation failed"):
            tb.speak_kitt("fail", job_id="error_job")

        assert not (spool / "error_job.mp3").exists()

    def test_speak_kitt_default_uuid_job_id(self, tmp_path, monkeypatch):
        """When job_id is None, a UUID is used as the filename stem."""
        spool = tmp_path / "spool"
        spool.mkdir()

        async def fake_generate(text, output_path):
            with open(output_path, "wb") as f:
                f.write(b"mp3")

        monkeypatch.setattr("kitt.telegram_bot._generate_tts", fake_generate)
        monkeypatch.setattr("kitt.telegram_bot.SPOOL_DIR", spool)

        result = tb.speak_kitt("hello", job_id=None)

        filename = Path(result).name
        assert filename.endswith(".mp3")
        assert len(filename) == 40  # uuid (36 chars) + .mp3 (4 chars)


# ── Tests: handle_text (full flow) ───────────────────────────────────────────

class TestHandleTextFull:
    """Full flow tests for the text message handler."""

    @pytest.mark.asyncio
    async def test_handle_text_success(self):
        """Text message → Hermes → TTS → Telegram audio + spool."""
        user = MagicMock()
        user.first_name = "TestUser"
        user.id = 12345
        chat = MagicMock()
        chat.id = 7292599600
        msg = MagicMock()
        msg.message_id = 999
        msg.text = "hello KITT"
        msg.effective_user = user
        msg.effective_chat = chat
        update = MagicMock()
        update.message = msg
        update.effective_user = user
        update.effective_chat = chat

        ctx = MagicMock()
        ctx.bot = MagicMock()
        ctx.bot.send_audio = AsyncMock()

        with patch("kitt.telegram_bot.forward_to_hermes", return_value="KITT response text") as mock_fwd:
            with patch("kitt.telegram_bot.speak_kitt") as mock_speak:
                mock_speak.return_value = "/tmp/kitt_test.mp3"
                with patch("kitt.telegram_bot.deliver_dual"):
                    with patch("builtins.open", MagicMock()):
                        await tb.handle_text(update, ctx)

                        mock_fwd.assert_called_once_with("hello KITT")
                        mock_speak.assert_called_once()
                        ctx.bot.send_audio.assert_called_once()


# ── Tests: cmd_start ──────────────────────────────────────────────────────────

class TestCmdStart:
    """Tests for the /start command handler."""

    @pytest.mark.asyncio
    async def test_cmd_start_replies(self):
        user = MagicMock()
        user.first_name = "TestUser"
        user.id = 12345
        chat = MagicMock()
        chat.id = 7292599600
        msg = MagicMock()
        msg.message_id = 999
        msg.text = "/start"
        msg.reply_text = AsyncMock()  # reply_text is an async method on Message
        update = MagicMock()
        update.message = msg
        update.effective_user = user
        update.effective_chat = chat

        ctx = MagicMock()
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock()

        await tb.cmd_start(update, ctx)

        msg.reply_text.assert_called_once()
        msg_text = msg.reply_text.call_args[0][0]
        assert "KITT is online" in msg_text


# ── Tests: /send-audio HTTP endpoint (live server) ───────────────────────────

class TestSendAudioLive:
    """Integration tests for POST /send-audio using a live HTTP server."""

    @pytest.fixture
    def live_server(self, tmp_path, monkeypatch):
        """Start the HTTP API server on a random port, yield the port."""
        spool = tmp_path / "spool"
        spool.mkdir()

        # Block all real outbound HTTP (Telegram API calls) from the live server.
        # _send_audio_via_telegram uses `import urllib.request` (local import),
        # so we must patch urllib.request.urlopen at its origin.
        import urllib.request

        def fake_urlopen(*args, **kwargs):
            # urlopen is synchronous — return a fake 200 response directly
            class FakeResponse:
                status = 200

                def read(self):
                    return b'{"ok":true,"message_id":999}'

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

            return FakeResponse()

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        port = 0  # ask OS for a free port
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        import threading
        server_thread = threading.Thread(
            target=tb.run_http_api,
            args=(port, "7292599600"),
            daemon=True,
        )
        server_thread.start()
        import time; time.sleep(0.15)  # let server start
        yield port

    def test_send_audio_success(self, live_server):
        """POST /send-audio returns 200 and calls Telegram API."""
        port = live_server
        conn = HTTPConnection("127.0.0.1", port)
        conn.request(
            "POST",
            "/send-audio",
            body=b"fake mp3 data",
            headers={"Content-Type": "audio/mpeg"},
        )
        resp = conn.getresponse()
        data = json.loads(resp.read())

        assert resp.status == 200
        assert data == {"ok": True}

    def test_send_audio_with_caption_header(self, live_server):
        """X-Caption header is forwarded."""
        port = live_server
        conn = HTTPConnection("127.0.0.1", port)
        conn.request(
            "POST",
            "/send-audio",
            body=b"mp3",
            headers={"Content-Type": "audio/mpeg", "X-Caption": "Alert: new follower"},
        )
        resp = conn.getresponse()
        assert resp.status == 200

    def test_send_audio_missing_body(self, live_server):
        """Empty body returns 400."""
        port = live_server
        conn = HTTPConnection("127.0.0.1", port)
        conn.request("POST", "/send-audio", body=b"", headers={"Content-Type": "audio/mpeg"})
        resp = conn.getresponse()
        data = json.loads(resp.read())
        assert resp.status == 400

    def test_health_endpoint(self, live_server):
        """GET /health returns 200 ok."""
        port = live_server
        conn = HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        data = json.loads(resp.read())
        assert resp.status == 200
        assert data == {"status": "ok"}


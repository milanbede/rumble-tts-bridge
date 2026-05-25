"""HTTP server for tts-server — serves MP3 files, handles ACK deletions,
and dispatches TTS announcements to Telegram.

Uses stdlib http.server only (no Flask/FastAPI).
"""

import http.server
import json
import os
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Any


class _Handler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for spooled MP3 files and Telegram dispatch.

    Routes:
      GET /              — JSON listing of files in spool dir
      GET /<name>.mp3   — file content with audio/mpeg content type
      POST /ack          — delete a file from spool dir
      POST /announce     — TTS + Telegram dispatch (event_type, text, tts_voice)
    """

    spool_dir: str = ""
    tts_engine: object = None
    telegram_conf: dict = {}

    # --------------------------------------------------------------------------
    # Route dispatch
    # --------------------------------------------------------------------------
    def do_GET(self):
        if self.path == "/" or self.path == "":
            self._list_files()
        elif self.path.startswith("/") and self.path.endswith(".mp3"):
            filename = self.path[1:]  # strip leading /
            self._serve_file(filename)
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path == "/ack":
            self._handle_ack()
        elif self.path == "/announce":
            self._handle_announce()
        else:
            self._send_json(404, {"error": "Not found"})

    # --------------------------------------------------------------------------
    # GET handlers
    # --------------------------------------------------------------------------
    def _serve_file(self, filename: str):
        """Serve filename.mp3 from spool_dir with audio/mpeg content type."""
        path = Path(self.spool_dir) / filename
        if not path.is_file():
            self._send_json(404, {"error": "File not found"})
            return
        try:
            with open(path, "rb") as f:
                content = f.read()
        except OSError:
            self._send_json(500, {"error": "Could not read file"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _list_files(self):
        """Return JSON listing of files in spool_dir."""
        try:
            files = []
            for entry in os.scandir(self.spool_dir):
                if entry.is_file() and entry.name.endswith(".mp3"):
                    stat = entry.stat()
                    files.append({
                        "filename": entry.name,
                        "size": stat.st_size,
                    })
        except OSError:
            self._send_json(500, {"error": "Could not list spool directory"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(files).encode())

    # --------------------------------------------------------------------------
    # POST handlers
    # --------------------------------------------------------------------------
    def _handle_ack(self):
        """Delete a file from spool dir.

        Body: {"filename": "x.mp3"}
        Returns 200 always (idempotent). Returns 400 if filename key is missing.
        """
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json(400, {"error": "Missing request body"})
            return

        try:
            body = self.rfile.read(content_length)
            payload = json.loads(body.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "Invalid JSON"})
            return

        if "filename" not in payload:
            self._send_json(400, {"error": "Missing 'filename' key"})
            return

        filename = payload["filename"]
        # Guard: prevent path traversal — filename must be just a name, not a path
        if os.path.basename(filename) != filename or filename != Path(filename).name:
            self._send_json(400, {"error": "Invalid filename"})
            return

        path = Path(self.spool_dir) / filename
        if path.is_file():
            path.unlink()
        # Idempotent: missing file is treated as success
        self._send_json(200, {"deleted": filename})

    def _handle_announce(self):
        """Generate TTS MP3 and send it + text to Telegram.

        Body: {
            "event_type": "subscription|chat|follow|gifted_sub|live_on|live_off",
            "text": "...",
            "tts_voice": "en-US-AriaNeural"   (optional, overrides engine default)
        }
        Returns 200 {"ok": true} or 500 {"error": "..."}
        """
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json(400, {"error": "Missing request body"})
            return

        try:
            body = self.rfile.read(content_length)
            payload = json.loads(body.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "Invalid JSON"})
            return

        text = payload.get("text", "").strip()
        if not text:
            self._send_json(400, {"error": "Missing 'text' field"})
            return

        event_type = payload.get("event_type", "unknown")
        tts_voice = payload.get("tts_voice")

        # Build job_id: announce_<event_type>_<timestamp>
        import time
        job_id = f"announce_{event_type}_{int(time.time() * 1000)}"

        # Generate MP3
        try:
            voice = tts_voice if tts_voice else self.tts_engine.voice
            # Temporarily override voice if different from engine default
            original_voice = None
            if tts_voice and tts_voice != self.tts_engine.voice:
                original_voice = self.tts_engine.voice
                self.tts_engine.voice = tts_voice

            mp3_path = self.tts_engine.speak(text, job_id=job_id)

            if original_voice is not None:
                self.tts_engine.voice = original_voice
        except Exception as exc:
            self._send_json(500, {"error": f"TTS generation failed: {exc}"})
            return

        # Send to Telegram
        try:
            token = self.telegram_conf["bot_token"]
            chat_id = self.telegram_conf["chat_id"]
            base_url = f"https://api.telegram.org/bot{token}"

            # 1. Send text message
            import urllib.error
            msg_payload = urllib.parse.urlencode({
                "chat_id": chat_id,
                "text": f"[{event_type}] {text}",
            })
            req = urllib.request.Request(
                f"{base_url}/sendMessage",
                data=msg_payload.encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    raise Exception(f"sendMessage returned {resp.status}")

            # 2. Send audio file
            with open(mp3_path, "rb") as audio_f:
                import io
                audio_data = audio_f.read()

            boundary = "----FormBoundary7h2k9s8d"
            body_parts: list[bytes] = [
                (f"--{boundary}\r\n"
                 f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n').encode(),
                (f"--{boundary}\r\n"
                 f'Content-Disposition: form-data; name="audio"; filename="{job_id}.mp3"\r\n'
                 f"Content-Type: audio/mpeg\r\n\r\n").encode(),
                audio_data,
                f"\r\n--{boundary}--\r\n".encode(),
            ]
            import email.mime.multipart
            req2 = urllib.request.Request(
                f"{base_url}/sendAudio",
                data=b"".join(body_parts),
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                },
            )
            with urllib.request.urlopen(req2, timeout=30) as resp2:
                if resp2.status != 200:
                    raise Exception(f"sendAudio returned {resp2.status}")

        except Exception as exc:
            self._send_json(500, {"error": f"Telegram dispatch failed: {exc}"})
            return
        finally:
            # Always clean up the temp MP3
            if os.path.exists(mp3_path):
                try:
                    os.remove(mp3_path)
                except OSError:
                    pass

        self._send_json(200, {"ok": True})

    # --------------------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------------------
    def _send_json(self, code: int, body: dict):
        """Send a JSON response with the given HTTP code and body dict."""
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    # --------------------------------------------------------------------------
    # Suppress noisy log
    # --------------------------------------------------------------------------
    def log_message(self, format: str, *args: Any):
        """Silence default request logging."""
        pass


# --------------------------------------------------------------------------
# Public factory
# --------------------------------------------------------------------------
def _make_handler(spool_dir: str, tts_engine, telegram_conf: dict):
    """Return a handler class bound to spool_dir, tts_engine, and telegram_conf."""
    def make_handler_class():
        class H(_Handler):
            pass
        H.spool_dir = spool_dir
        H.tts_engine = tts_engine
        H.telegram_conf = telegram_conf
        return H
    return make_handler_class()


def _create_httpd(host: str, port: int, handler):
    """Create and return a configured HTTPServer."""
    httpd = http.server.HTTPServer((host, port), handler)
    return httpd


def make_app(spool_dir: str, host: str, port: int, tts_engine=None, telegram_conf=None):
    """Create and start a running HTTP server.

    Args:
        spool_dir: directory containing MP3 files to serve
        host: address to bind to
        port: port to listen on
        tts_engine: TTSEngine instance for /announce endpoint
        telegram_conf: dict with `bot_token` and `chat_id` keys

    Returns:
        The running HTTPServer instance.
    """
    if tts_engine is None:
        raise ValueError("tts_engine is required for /announce endpoint")
    if telegram_conf is None:
        telegram_conf = {}
    handler = _make_handler(spool_dir, tts_engine, telegram_conf)
    httpd = _create_httpd(host, port, handler)
    # Run in a daemon thread so make_app() returns immediately and the server
    # keeps running in the background.
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


import threading  # noqa: E402
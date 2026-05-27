"""HTTP server for tts-server — serves MP3 files, handles ACK deletions,
and dispatches TTS announcements to the KITT bot (which forwards to Telegram).

Uses stdlib http.server only (no Flask/FastAPI).
"""

import http.server
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import httpx

PI_ZERO_IP = "100.89.216.54"
PI_ZERO_PORT = 8081


class _Handler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for spooled MP3 files and Telegram dispatch.

    Routes:
      GET /              — JSON listing of files in spool dir
      GET /<name>.mp3   — file content with audio/mpeg content type
      POST /ack          — delete a file from spool dir
      POST /announce     — TTS + KITT bot dispatch (event_type, text, tts_voice)
    """

    spool_dir: str = ""
    tts_engine: object = None
    telegram_conf: dict = {}
    kitt_bot_url: str = "http://127.0.0.1:8082"

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
        elif self.path == "/announce-tts":
            self._handle_announce_tts()
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

    def _kitt_intro(self, event_type: str, text: str) -> str:
        """Prepend KITT-style voice personality intro based on event type."""
        intro_map = {
            "subscription": f"KITT here. {text}",
            "follow":       f"KITT here. New follower: {text}",
            "gifted_sub":   f"KITT here. {text}",
            "chat":         f"KITT here. {text}",
            "live_on":      "KITT here. Stream is live.",
            "live_off":     "KITT here. Stream has ended.",
        }
        return intro_map.get(event_type, f"KITT here. {text}")

    def _handle_announce(self):
        """Generate TTS MP3 and send it to the KITT bot for Telegram delivery.

        Body: {
            "event_type": "subscription|chat|follow|gifted_sub|live_on|live_off",
            "text": "...",
            "tts_voice": "en-US-AriaNeural"   (optional, overrides engine default)
        }
        Returns 200 {"ok": true} or 500 {"error": "..."}

        The KITT bot (kitt/telegram_bot.py) holds the single Telegram bot token
        and runs the long-polling loop. This server POSTs the MP3 to the bot's
        /send-audio HTTP endpoint to avoid the token-conflict issue.
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

        # Apply KITT voice personality intro
        text = self._kitt_intro(event_type, text)

        # Build job_id: announce_<event_type>_<timestamp>
        import time
        job_id = f"announce_{event_type}_{int(time.time() * 1000)}"

        # Generate MP3
        try:
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

        # Send to KITT bot via /send-audio endpoint
        try:
            with open(mp3_path, "rb") as audio_f:
                mp3_data = audio_f.read()

            caption = f"[{event_type}] {text}"
            req = urllib.request.Request(
                self.kitt_bot_url,
                data=mp3_data,
                headers={
                    "Content-Type": "audio/mpeg",
                    "X-Caption": caption,
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status != 200:
                    raise Exception(f"/send-audio returned {resp.status}")

        except Exception as exc:
            self._send_json(500, {"error": f"KITT bot dispatch failed: {exc}"})
            return
        finally:
            if os.path.exists(mp3_path):
                try:
                    os.remove(mp3_path)
                except OSError:
                    pass

        self._send_json(200, {"ok": True})

    def _handle_announce_tts(self):
        """Generate TTS MP3 and POST it to the Pi Zero TTS endpoint.

        Body: {"text": "...", "voice": "en-US-JennyNeural"} (voice is optional)
        Returns 200 {"status": "sent", "size": N} or 500 {"error": "..."}
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

        voice = payload.get("voice", "en-US-JennyNeural")

        # Generate MP3
        import time
        job_id = f"announce_tts_{int(time.time() * 1000)}"
        try:
            original_voice = None
            if voice != self.tts_engine.voice:
                original_voice = self.tts_engine.voice
                self.tts_engine.voice = voice
            mp3_path = self.tts_engine.speak(text, job_id=job_id)
            if original_voice is not None:
                self.tts_engine.voice = original_voice
        except Exception as exc:
            self._send_json(500, {"error": f"TTS generation failed: {exc}"})
            return

        try:
            with open(mp3_path, "rb") as f:
                mp3_data = f.read()
        except OSError as exc:
            self._send_json(500, {"error": f"Could not read MP3: {exc}"})
            return
        finally:
            if os.path.exists(mp3_path):
                try:
                    os.remove(mp3_path)
                except OSError:
                    pass

        # Send to Pi Zero
        try:
            async def _send():
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        f"http://{PI_ZERO_IP}:{PI_ZERO_PORT}/tts",
                        content=mp3_data,
                        headers={"Content-Type": "audio/mpeg"},
                    )
                    resp.raise_for_status()
                return {"status": "sent", "size": len(mp3_data)}

            import asyncio
            result = asyncio.run(_send())
        except Exception as exc:
            self._send_json(500, {"error": f"Pi Zero dispatch failed: {exc}"})
            return

        self._send_json(200, result)

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
def _make_handler(spool_dir: str, tts_engine, telegram_conf: dict, kitt_bot_url: str = "http://127.0.0.1:8082"):
    """Return a handler class bound to spool_dir, tts_engine, telegram_conf, and kitt_bot_url."""
    def make_handler_class():
        class H(_Handler):
            pass
        H.spool_dir = spool_dir
        H.tts_engine = tts_engine
        H.telegram_conf = telegram_conf
        H.kitt_bot_url = kitt_bot_url
        return H
    return make_handler_class()


def _create_httpd(host: str, port: int, handler):
    """Create and return a configured HTTPServer."""
    httpd = http.server.HTTPServer((host, port), handler)
    return httpd


def make_app(spool_dir: str, host: str, port: int, tts_engine=None, telegram_conf=None, kitt_bot_url: str = "http://127.0.0.1:8082"):
    """Create and start a running HTTP server.

    Args:
        spool_dir: directory containing MP3 files to serve
        host: address to bind to
        port: port to listen on
        tts_engine: TTSEngine instance for /announce endpoint
        telegram_conf: dict with `bot_token` and `chat_id` keys (deprecated — no longer used directly)
        kitt_bot_url: base URL of the KITT bot's HTTP API (default: http://127.0.0.1:8082)

    Returns:
        The running HTTPServer instance.
    """
    if tts_engine is None:
        raise ValueError("tts_engine is required for /announce endpoint")
    if telegram_conf is None:
        telegram_conf = {}
    handler = _make_handler(spool_dir, tts_engine, telegram_conf, kitt_bot_url=kitt_bot_url)
    httpd = _create_httpd(host, port, handler)
    # Run in a daemon thread so make_app() returns immediately and the server
    # keeps running in the background.
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


import threading  # noqa: E402
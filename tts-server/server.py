"""HTTP server for tts-server — serves MP3 files and handles ACK deletions.

Uses stdlib http.server only (no Flask/FastAPI).
"""

import http.server
import json
import os
from pathlib import Path
from typing import Any


class _Handler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for spooled MP3 files.

    Routes:
      GET /              — JSON listing of files in spool dir
      GET /<name>.mp3   — file content with audio/mpeg content type
      POST /ack          — delete a file from spool dir
    """

    spool_dir: str = ""

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
def _make_handler(spool_dir: str):
    """Return a handler class bound to *spool_dir*."""
    def make_handler_class():
        class H(_Handler):
            pass
        H.spool_dir = spool_dir
        return H
    return make_handler_class()


def _create_httpd(host: str, port: int, handler):
    """Create and return a configured HTTPServer."""
    httpd = http.server.HTTPServer((host, port), handler)
    return httpd


def make_app(spool_dir: str, host: str, port: int):
    """Create and start a running HTTP server.

    Args:
        spool_dir: directory containing MP3 files to serve
        host: address to bind to
        port: port to listen on

    Returns:
        The running HTTPServer instance.
    """
    handler = _make_handler(spool_dir)
    httpd = _create_httpd(host, port, handler)
    # Run in a daemon thread so make_app() returns immediately and the server
    # keeps running in the background.
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


import threading  # noqa: E402
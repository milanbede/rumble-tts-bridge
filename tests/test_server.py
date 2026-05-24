"""Tests for tts-server HTTP server."""

import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest
import requests

# Load server.py from tts-server using importlib
TTS_SERVER_DIR = os.path.join(os.path.dirname(__file__), "..", "tts-server")
_SERVER_MODULE = None


def _load_server_module():
    global _SERVER_MODULE
    if _SERVER_MODULE is not None:
        return _SERVER_MODULE
    spec = importlib.util.spec_from_file_location(
        "tts_server_server", os.path.join(TTS_SERVER_DIR, "server.py")
    )
    sys.path.insert(0, TTS_SERVER_DIR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _SERVER_MODULE = mod
    return mod


def _find_free_port() -> int:
    """Return an available port on 127.0.0.1 to avoid binding conflicts."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestHTTPServer:
    """HTTP server tests using requests hitting localhost."""

    @pytest.fixture
    def spool_dir(self, tmp_path):
        """Create a temporary spool directory."""
        d = tmp_path / "spool"
        d.mkdir()
        return str(d)

    @pytest.fixture
    def server_base_url(self, spool_dir):
        """Start server in thread and yield its base URL, then shut it down."""
        server_mod = _load_server_module()
        port = _find_free_port()
        handler = server_mod._make_handler(spool_dir)
        httpd = server_mod._create_httpd("127.0.0.1", port, handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.1)  # let server bind

        base_url = f"http://127.0.0.1:{port}"
        yield base_url

        httpd.shutdown()
        thread.join(timeout=5)

    # --------------------------------------------------------------------------
    # GET /{filename}.mp3
    # --------------------------------------------------------------------------
    def test_get_mp3_returns_200(self, spool_dir, server_base_url):
        """GET /existing.mp3 returns 200 with audio/mpeg content type."""
        mp3_path = Path(spool_dir) / "test.mp3"
        mp3_path.write_bytes(b"fake mp3 data" * 100)

        resp = requests.get(f"{server_base_url}/test.mp3")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"] == "audio/mpeg"
        assert resp.content == b"fake mp3 data" * 100

    def test_get_nonexistent_mp3_returns_404(self, server_base_url):
        """GET /nonexistent.mp3 returns 404."""
        resp = requests.get(f"{server_base_url}/nonexistent.mp3")
        assert resp.status_code == 404

    # --------------------------------------------------------------------------
    # GET /
    # --------------------------------------------------------------------------
    def test_get_root_returns_json_listing(self, spool_dir, server_base_url):
        """GET / returns 200 with JSON listing files in spool dir."""
        for name in ["a.mp3", "b.mp3"]:
            (Path(spool_dir) / name).write_bytes(b"data")

        resp = requests.get(f"{server_base_url}/")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"] == "application/json"
        files = resp.json()
        filenames = [f["filename"] for f in files]
        assert "a.mp3" in filenames
        assert "b.mp3" in filenames

    # --------------------------------------------------------------------------
    # POST /ack
    # --------------------------------------------------------------------------
    def test_post_ack_deletes_file(self, spool_dir, server_base_url):
        """POST /ack with filename deletes the file and returns 200."""
        mp3_path = Path(spool_dir) / "to_delete.mp3"
        mp3_path.write_bytes(b"delete me")

        resp = requests.post(
            f"{server_base_url}/ack",
            json={"filename": "to_delete.mp3"},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        assert not mp3_path.exists()

    def test_post_ack_nonexistent_is_idempotent(self, server_base_url):
        """POST /ack with nonexistent file returns 200 (idempotent)."""
        resp = requests.post(
            f"{server_base_url}/ack",
            json={"filename": "does_not_exist.mp3"},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200

    def test_post_ack_missing_filename_returns_400(self, server_base_url):
        """POST /ack without filename key returns 400."""
        resp = requests.post(
            f"{server_base_url}/ack",
            json={},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    # --------------------------------------------------------------------------
    # Concurrent requests
    # --------------------------------------------------------------------------
    def test_concurrent_get_requests(self, spool_dir, server_base_url):
        """Multiple concurrent GET requests are handled correctly."""
        mp3_path = Path(spool_dir) / "concurrent.mp3"
        mp3_path.write_bytes(b"concurrent data" * 50)

        def get_once():
            resp = requests.get(f"{server_base_url}/concurrent.mp3")
            return resp.status_code, resp.content

        results = []
        threads = []
        for _ in range(10):
            t = threading.Thread(target=lambda: results.append(get_once()))
            threads.append(t)
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for status, content in results:
            assert status == 200
            assert content == b"concurrent data" * 50

    # --------------------------------------------------------------------------
    # make_app integration
    # --------------------------------------------------------------------------
    def test_make_app_returns_running_server(self, spool_dir):
        """make_app(spool_dir, host, port) returns a running HTTPServer."""
        server_mod = _load_server_module()
        port = _find_free_port()
        httpd = server_mod.make_app(spool_dir, "127.0.0.1", port)

        try:
            assert httpd is not None
            # Server should be responsive
            resp = requests.get(f"http://127.0.0.1:{port}/")
            assert resp.status_code == 200
        finally:
            httpd.shutdown()
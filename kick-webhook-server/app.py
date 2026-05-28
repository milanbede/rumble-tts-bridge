"""Flask webhook server for Kick — wires signature verification, event mapping, and TTS."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any

from flask import Flask, Request, Response, jsonify, request
from flask.wrappers import Response as FlaskResponse

from events import _map_kick_event
from oauth import get_valid_token
from signature import verify_signature
from state import StateStore
from tts_speaker import get_or_create_player

log = logging.getLogger(__name__)


def create_app(config: dict[str, Any]) -> Flask:
    """Factory: build and configure the Flask application.

    Args:
        config: Full loaded config dict with ``kick``, ``server``, ``tts``, ``events`` sections.

    Returns:
        Configured Flask app ready for ``test_client()`` or ``run_server()``.
    """
    app = Flask(__name__)

    # Lazily-created TTS player (one per voice, shared across requests)
    _tts_player = None

    # StateStore and OAuth token (loaded from config)
    spool_dir = config["server"].get("spool_dir")
    tts_server_url = config["server"].get("tts_server_url", "http://localhost:8080")
    _state_store = StateStore(spool_dir) if spool_dir else None
    _oauth_token = None

    def get_tts_player():
        nonlocal _tts_player
        if _tts_player is None:
            _tts_player = get_or_create_player(config["tts"])
        return _tts_player

    def get_oauth_token():
        nonlocal _oauth_token
        _oauth_token = get_valid_token(
            config["kick"]["client_id"],
            config["kick"]["client_secret"],
            spool_dir,
            _oauth_token,
        )
        return _oauth_token

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @app.route("/health", methods=["GET"])
    def health():
        """Liveness probe — no auth required."""
        return jsonify({"status": "ok"})

    @app.route("/webhook", methods=["POST"])
    def webhook():
        """Receive and process a Kick webhook event."""
        # 1. Raw request body
        body_bytes: bytes = request.get_data()

        # 2. Signature header
        sig_header: str = request.headers.get("X-Kick-Signature", "")

        # 3. Verify ECDSA signature
        public_key_pem = config["kick"]["public_key_pem"]
        if not verify_signature(body_bytes, sig_header, public_key_pem):
            log.warning("Invalid webhook signature")
            return Response("Forbidden", status=403)

        # 4. Parse JSON body
        try:
            event: dict[str, Any] = json.loads(body_bytes)
        except json.JSONDecodeError:
            log.warning("Malformed JSON in webhook payload")
            return Response("Bad Request", status=400)

        # 5. Deduplicate via StateStore
        event_type = event.get("event", "")
        event_id = event.get("id", "")
        if _state_store and event_id and _state_store.seen(event_type, event_id):
            log.debug("Duplicate event %s/%s — returning 204", event_type, event_id)
            return Response(status=204)
        if _state_store:
            _state_store.mark(event_type, event_id)

        # 6. Map to TTS text — 204 if None (disabled / unknown event)
        tts_text = _map_kick_event(event, config["events"])
        if tts_text is None:
            log.debug("No TTS text for event %s — returning 204", event_type)
            return Response(status=204)

        # 7. Obtain OAuth token
        get_oauth_token()

        # 8. Generate MP3 to spool_dir
        if not spool_dir:
            log.error("spool_dir not configured — cannot write MP3")
            return Response("Internal Server Error", status=500)

        os.makedirs(spool_dir, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.mp3"
        mp3_path = os.path.join(spool_dir, filename)

        player = get_tts_player()
        try:
            asyncio.create_task(player.speak_to_file(tts_text, mp3_path))
        except RuntimeError:
            # No running event loop (e.g., in test client) — run in a background thread
            import threading

            def _background_speak():
                asyncio.run(player.speak_to_file(tts_text, mp3_path))

            threading.Thread(target=_background_speak, daemon=True).start()

        # 9. Return 204
        log.info("Queued TTS for event %s: %s -> %s", event_type, tts_text, mp3_path)
        return Response(status=204)

    # ------------------------------------------------------------------
    # Global exception handlers
    # ------------------------------------------------------------------

    @app.errorhandler(json.JSONDecodeError)
    def handle_json_decode_error(exc):
        """400 for any JSON parse failure that slips through."""
        return Response("Bad Request", status=400)

    return app


def run_server(config: dict[str, Any]) -> None:
    """Run the Flask app with host/port from *config*."""
    host = config["server"]["host"]
    port = config["server"]["port"]
    app = create_app(config)
    app.run(host=host, port=port, threaded=True)
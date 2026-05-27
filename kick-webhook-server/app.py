"""Flask webhook server for Kick — wires signature verification, event mapping, and TTS."""

from __future__ import annotations

import json
import logging
from typing import Any

from flask import Flask, Request, Response, jsonify, request
from flask.wrappers import Response as FlaskResponse

from events import _map_kick_event
from signature import verify_signature
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

    def get_tts_player():
        nonlocal _tts_player
        if _tts_player is None:
            _tts_player = get_or_create_player(config["tts"])
        return _tts_player

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

        # 5. Map to TTS text — 204 if None (disabled / unknown event)
        tts_text = _map_kick_event(event, config["events"])
        if tts_text is None:
            log.debug("No TTS text for event %s — returning 204", event.get("event"))
            return Response(status=204)

        # 6. Speak asynchronously (fire-and-forget)
        player = get_tts_player()
        asyncio = __import__("asyncio")
        try:
            asyncio.create_task(player.speak(tts_text))
        except RuntimeError:
            # No running event loop (e.g., in test client) — run in a background thread
            import threading

            def _background_speak():
                asyncio.run(player.speak(tts_text))

            threading.Thread(target=_background_speak, daemon=True).start()

        # 7. Return 204
        log.info("Queued TTS for event %s: %s", event.get("event"), tts_text)
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
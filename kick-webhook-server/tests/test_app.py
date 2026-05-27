"""Tests for kick-webhook-server Flask app."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app import create_app


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

def minimal_config(overrides=None):
    """Return a minimal valid config dict, optionally merged with *overrides*."""
    cfg = {
        "kick": {
            "oauth_token": "test_token",
            "client_id": "test_client",
            "client_secret": "test_secret",
            "broadcaster_user_id": 123456,
            "public_key_pem": (
                "-----BEGIN PUBLIC KEY-----\n"
                "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAETest\n"
                "-----END PUBLIC KEY-----"
            ),
        },
        "server": {
            "host": "127.0.0.1",
            "port": 9000,
            "spool_dir": "/tmp/spool",
        },
        "tts": {
            "voice": "en-US-JennyNeural",
            "rate": "+10%",
            "volume": "+20%",
        },
        "events": {
            "channel.followed": True,
            "channel.subscription.new": True,
            "channel.subscription.gifts": True,
            "channel.subscription.renewal": False,
            "chat.message.sent": False,
        },
    }
    if overrides:
        for section, keys in overrides.items():
            cfg[section].update(keys)
    return cfg


def valid_signature_header(timestamp="1234567890"):
    """Return a well-formed X-Kick-Signature header."""
    return f"t={timestamp},v1=dGVzdF9zaWduYXR1cmU="


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    """Test GET /health."""

    def test_health_returns_200_and_ok(self):
        app = create_app(minimal_config())
        client = app.test_client()
        response = client.get("/health")
        assert response.status_code == 200
        assert response.get_json() == {"status": "ok"}


class TestWebhookSignatureVerification:
    """Test POST /webhook signature handling."""

    def test_valid_signature_returns_204(self):
        config = minimal_config()
        app = create_app(config)
        client = app.test_client()

        payload = json.dumps({"event": "channel.followed", "data": {"user": {"username": "testuser"}}})

        with patch("app.verify_signature", return_value=True):
            with patch("app.get_or_create_player") as mock_get_player:
                mock_player = AsyncMock()
                mock_player.speak = AsyncMock()
                mock_get_player.return_value = mock_player

                response = client.post(
                    "/webhook",
                    data=payload,
                    content_type="application/json",
                    headers={"X-Kick-Signature": valid_signature_header()},
                )

        assert response.status_code == 204

    def test_invalid_signature_returns_403(self):
        config = minimal_config()
        app = create_app(config)
        client = app.test_client()

        payload = json.dumps({"event": "channel.followed", "data": {"user": {"username": "testuser"}}})

        with patch("app.verify_signature", return_value=False):
            response = client.post(
                "/webhook",
                data=payload,
                content_type="application/json",
                headers={"X-Kick-Signature": "t=1234567890,v1=invalid"},
            )

        assert response.status_code == 403

    def test_missing_signature_returns_403(self):
        config = minimal_config()
        app = create_app(config)
        client = app.test_client()

        payload = json.dumps({"event": "channel.followed", "data": {"user": {"username": "testuser"}}})

        # verify_signature returns False for empty header
        with patch("app.verify_signature", return_value=False):
            response = client.post(
                "/webhook",
                data=payload,
                content_type="application/json",
                # no X-Kick-Signature header
            )

        assert response.status_code == 403


class TestWebhookMalformedJSON:
    """Test POST /webhook with invalid JSON payloads."""

    def test_malformed_json_returns_400(self):
        config = minimal_config()
        app = create_app(config)
        client = app.test_client()

        with patch("app.verify_signature", return_value=True):
            response = client.post(
                "/webhook",
                data=b"not valid json {",
                content_type="application/json",
                headers={"X-Kick-Signature": valid_signature_header()},
            )

        assert response.status_code == 400


class TestWebhookDisabledEvent:
    """Test POST /webhook with a disabled event type — should return 204 without TTS call."""

    def test_disabled_event_returns_204_no_tts(self):
        config = minimal_config(overrides={
            "events": {
                "channel.followed": True,
                "channel.subscription.new": True,
                "channel.subscription.gifts": True,
                "channel.subscription.renewal": False,  # disabled
                "chat.message.sent": False,             # disabled
            }
        })
        app = create_app(config)
        client = app.test_client()

        payload = json.dumps({
            "event": "channel.subscription.renewal",
            "data": {"user": {"username": "reneweduser"}},
        })

        with patch("app.verify_signature", return_value=True):
            with patch("app.get_or_create_player") as mock_get_player:
                mock_player = AsyncMock()
                mock_player.speak = AsyncMock()
                mock_get_player.return_value = mock_player

                response = client.post(
                    "/webhook",
                    data=payload,
                    content_type="application/json",
                    headers={"X-Kick-Signature": valid_signature_header()},
                )

        assert response.status_code == 204
        # speak should NOT have been called because renewal is disabled
        mock_player.speak.assert_not_called()
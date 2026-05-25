"""Tests for RumblePoller — R3 of SPEC:tts-server."""

import json
import time
import sys
import os
import itertools
import requests
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tts-server"))
from poller import RumblePoller, Event


# ---------------------------------------------------------------------------
# Sample payloads
# ---------------------------------------------------------------------------

SAMPLE_PAYLOAD = {
    "latest_follower": {"username": "Alice", "followed_at": "2026-05-24T10:00:00Z"},
    "new_subscribers": [
        {"username": "Bob", "amount": 5.0, "tier": "prime"},
    ],
    "gifted_subs": [
        {"purchased_by": "Charlie", "total": 3},
    ],
    "stream": {"is_live": True, "title": "Live Stream"},
    "chat_messages": [
        {"username": "Eve", "message": "Hello world!", "timestamp": "2026-05-24T10:01:00Z"},
    ],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_state():
    state = MagicMock()
    state.seen.return_value = False
    return state


@pytest.fixture
def default_config():
    return {
        "poll_interval_seconds": 30,
        "new_follower": True,
        "new_subscriber": True,
        "gifted_sub": True,
        "live_on": True,
        "live_off": False,
        "chat_message": True,
    }


@pytest.fixture
def poller(mock_state, default_config):
    return RumblePoller(
        api_url="https://rumble.com/-livestream-api/get-data",
        api_key="test-key",
        state=mock_state,
        config=default_config,
    )


# ---------------------------------------------------------------------------
# R3.1 — constructor stores all params
# ---------------------------------------------------------------------------

def test_constructor_stores_all_params(mock_state, default_config):
    p = RumblePoller("http://example.com", "my-key", mock_state, default_config)
    assert p._api_url == "http://example.com"
    assert p._api_key == "my-key"
    assert p._state is mock_state
    assert p._config is default_config


# ---------------------------------------------------------------------------
# R3.2 — poll() calls API with key as query param (not Bearer header)
# ---------------------------------------------------------------------------

def test_poll_calls_api_with_key_query_param(poller):
    with patch("requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        poller.poll()

        mock_get.assert_called_once_with(
            "https://rumble.com/-livestream-api/get-data",
            params={"key": "test-key"},
            timeout=10,
        )


# ---------------------------------------------------------------------------
# R3.3 — Network failure returns [] (no exception raised)
# ---------------------------------------------------------------------------

def test_poll_returns_empty_on_network_failure(poller):
    with patch("requests.get", side_effect=requests.exceptions.RequestException("network error")):
        result = poller.poll()
        assert result == []


# ---------------------------------------------------------------------------
# R3.4 — _extract_events produces new_follower event for latest_follower
# ---------------------------------------------------------------------------

def test_extract_events_new_follower(poller, mock_state):
    events = poller._extract_events(SAMPLE_PAYLOAD)
    follower_events = [e for e in events if e.type == "new_follower"]
    assert len(follower_events) == 1
    assert follower_events[0].text == "New follower: Alice"


# ---------------------------------------------------------------------------
# R3.5 — Duplicate latest_follower.username is skipped
# ---------------------------------------------------------------------------

def test_duplicate_follower_skipped(poller, mock_state):
    mock_state.seen.return_value = False
    events1 = poller._extract_events(SAMPLE_PAYLOAD)
    assert any(e.type == "new_follower" for e in events1)

    mock_state.seen.return_value = True
    events2 = poller._extract_events(SAMPLE_PAYLOAD)
    assert not any(e.type == "new_follower" for e in events2)


# ---------------------------------------------------------------------------
# R3.6 — new_subscriber event text
# ---------------------------------------------------------------------------

def test_new_subscriber_event_text(poller, mock_state):
    events = poller._extract_events(SAMPLE_PAYLOAD)
    sub_events = [e for e in events if e.type == "new_subscriber"]
    assert len(sub_events) == 1
    assert sub_events[0].text == "New subscriber: Bob, 5.0 dollars"


# ---------------------------------------------------------------------------
# R3.7 — gifted_sub event text
# ---------------------------------------------------------------------------

def test_gifted_sub_event_text(poller, mock_state):
    events = poller._extract_events(SAMPLE_PAYLOAD)
    gifted_events = [e for e in events if e.type == "gifted_sub"]
    assert len(gifted_events) == 1
    assert gifted_events[0].text == "Gifted sub from Charlie"


# ---------------------------------------------------------------------------
# R3.8 — live_on fires when is_live: true and wasn't live before
# ---------------------------------------------------------------------------

def test_live_on_fires_when_stream_goes_live(poller, mock_state):
    payload = {"stream": {"is_live": True}}
    events = poller._extract_events(payload)
    assert any(e.type == "live_on" for e in events)


# ---------------------------------------------------------------------------
# R3.9 — live_off fires when is_live: false and live_off is enabled
# ---------------------------------------------------------------------------

def test_live_off_fires_when_stream_goes_offline(mock_state):
    config = {
        "poll_interval_seconds": 30,
        "new_follower": False,
        "new_subscriber": False,
        "gifted_sub": False,
        "live_on": False,
        "live_off": True,
        "chat_message": False,
    }
    poller = RumblePoller(
        api_url="https://rumble.com/-livestream-api/get-data",
        api_key="test-key",
        state=mock_state,
        config=config,
    )
    payload = {"stream": {"is_live": False}}
    events = poller._extract_events(payload)
    assert any(e.type == "live_off" for e in events)


# ---------------------------------------------------------------------------
# R3.10 — live_off is NOT emitted when live_off config is False
# ---------------------------------------------------------------------------

def test_live_off_not_emitted_when_disabled(poller):
    payload = {"stream": {"is_live": False}}
    events = poller._extract_events(payload)
    assert not any(e.type == "live_off" for e in events)


# ---------------------------------------------------------------------------
# R3.11 — chat_message event text format
# ---------------------------------------------------------------------------

def test_chat_message_event_text(poller, mock_state):
    events = poller._extract_events(SAMPLE_PAYLOAD)
    chat_events = [e for e in events if e.type == "chat_message"]
    assert len(chat_events) == 1
    assert chat_events[0].text == "Eve said: Hello world!"


# ---------------------------------------------------------------------------
# R3.12 — poll() returns empty list on malformed JSON (no exception)
# ---------------------------------------------------------------------------

def test_poll_returns_empty_on_malformed_json(poller):
    with patch("requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Invalid", "", 0)
        mock_response.text = "not valid json"
        mock_get.return_value = mock_response

        result = poller.poll()
        assert result == []


# ---------------------------------------------------------------------------
# R3.13 — poll() handles 429 rate limit gracefully with backoff
# ---------------------------------------------------------------------------

def test_poll_handles_429_rate_limit(poller):
    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.headers = {"Retry-After": "60"}

    with patch("requests.get", return_value=mock_response) as mock_get, \
         patch("time.sleep") as mock_sleep:
        result = poller.poll()
        assert result == []
        mock_get.assert_called_once()
        mock_sleep.assert_called_once_with(60)


# ---------------------------------------------------------------------------
# R3.14 — poll() handles 5xx errors with exponential backoff
# ---------------------------------------------------------------------------

def test_poll_handles_5xx_with_backoff(poller):
    mock_response = MagicMock()
    mock_response.status_code = 503

    with patch("requests.get", return_value=mock_response) as mock_get, \
         patch("time.sleep") as mock_sleep:
        result = poller.poll()
        assert result == []
        # First backoff is 30s (min)
        mock_sleep.assert_called_once_with(30)
        # Backoff should double for next 5xx
        assert poller._backoff == 60


# ---------------------------------------------------------------------------
# R3.15 — run(callback) calls callback for each new event, then sleeps
# ---------------------------------------------------------------------------

def test_run_calls_callback_for_each_event_and_sleeps(mock_state, default_config):
    callback = MagicMock()

    poller = RumblePoller(
        api_url="https://rumble.com/-livestream-api/get-data",
        api_key="test-key",
        state=mock_state,
        config=default_config,
    )

    with patch("requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_PAYLOAD
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        cycle = itertools.count()

        def controlled_sleep(seconds):
            if next(cycle) == 0:
                raise KeyboardInterrupt("test: exit after first poll")

        with patch("time.sleep", side_effect=controlled_sleep):
            try:
                poller.run(callback)
            except KeyboardInterrupt:
                pass

        assert callback.call_count >= 1


# ---------------------------------------------------------------------------
# Event dataclass tests
# ---------------------------------------------------------------------------

def test_event_dataclass():
    e = Event(type="test", text="hello", event_id="123")
    assert e.type == "test"
    assert e.text == "hello"
    assert e.event_id == "123"
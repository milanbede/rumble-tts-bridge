"""RumblePoller — polls Rumble Live Stream API and extracts typed events."""

import logging
import time
from dataclasses import dataclass
from typing import Callable

import requests

log = logging.getLogger(__name__)


@dataclass
class Event:
    """A Rumble event to be TTS'd."""

    type: str
    text: str
    event_id: str


class RumblePoller:
    """Polls the Rumble API on a schedule and emits typed events."""

    def __init__(
        self,
        api_url: str,
        api_key: str,
        state,  # duck-typed: StateStore with seen() / mark()
        config: dict,
    ):
        self._api_url = api_url
        self._api_key = api_key
        self._state = state
        self._config = config
        self._backoff = 0  # seconds, resets after successful poll

    def poll(self) -> list[Event]:
        """Fetch the latest update from the Rumble API.

        Returns:
            List of Event objects. Empty list on any failure (network,
            malformed JSON, rate-limit, etc.) — never raises.
        """
        try:
            response = requests.get(
                self._api_url,
                params={"key": self._api_key},
                timeout=10,
            )

            # Handle HTTP-level errors with backoff
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", self._config.get("poll_interval_seconds", 30)))
                log.warning("Rate-limited (429). Retrying in %ds", retry_after)
                time.sleep(retry_after)
                return []

            if response.status_code >= 500:
                log.warning("Server error %d from Rumble API. Backing off %ds",
                            response.status_code, self._backoff or 30)
                time.sleep(self._backoff or 30)
                self._backoff = min((self._backoff or 30) * 2, 300)  # cap at 5 minutes
                return []

            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.Timeout:
            log.warning("Request timed out reaching Rumble API.")
            return []
        except requests.exceptions.RequestException as exc:
            log.warning("Request failed: %s", exc)
            return []
        except ValueError as exc:  # includes JSONDecodeError
            log.warning("Malformed JSON from Rumble API: %s", exc)
            return []

        # Successful poll — reset backoff
        self._backoff = 0
        return self._extract_events(payload)

    def _extract_events(self, payload: dict) -> list[Event]:
        """Extract typed events from a Rumble API payload."""
        events: list[Event] = []
        seen = self._state.seen

        # --- latest_follower ---
        if self._config.get("new_follower") and "latest_follower" in payload:
            follower = payload["latest_follower"]
            username = follower.get("username", "")
            event_id = f"follower/{username}"
            if username and not seen("follower", username):
                events.append(Event(type="new_follower", text=f"New follower: {username}", event_id=event_id))
                self._state.mark("follower", username)
                log.info("New follower: %s", username)

        # --- new_subscribers ---
        if self._config.get("new_subscriber") and "new_subscribers" in payload:
            for sub in payload["new_subscribers"]:
                username = sub.get("username", "")
                amount = sub.get("amount", "")
                event_id = f"subscriber/{username}"
                if username and not seen("subscriber", username):
                    text = f"New subscriber: {username}, {amount} dollars"
                    events.append(Event(type="new_subscriber", text=text, event_id=event_id))
                    self._state.mark("subscriber", username)
                    log.info("New subscriber: %s (%s)", username, amount)

        # --- gifted_subs ---
        if self._config.get("gifted_sub") and "gifted_subs" in payload:
            for gift in payload["gifted_subs"]:
                purchased_by = gift.get("purchased_by", "")
                event_id = f"gifted_sub/{purchased_by}"
                if purchased_by and not seen("gifted_sub", purchased_by):
                    text = f"Gifted sub from {purchased_by}"
                    events.append(Event(type="gifted_sub", text=text, event_id=event_id))
                    self._state.mark("gifted_sub", purchased_by)
                    log.info("Gifted sub from: %s", purchased_by)

        # --- chat_messages ---
        if self._config.get("chat_message") and "chat_messages" in payload:
            for msg in payload["chat_messages"]:
                username = msg.get("username", "")
                message = msg.get("message", "")
                event_id = f"chat/{username}/{message[:32]}"
                if username and message and not seen("chat", event_id):
                    text = f"{username} said: {message}"
                    events.append(Event(type="chat_message", text=text, event_id=event_id))
                    self._state.mark("chat", event_id)
                    log.info("Chat: %s: %s", username, message[:50])

        # --- stream live state ---
        stream = payload.get("stream", {})
        is_live = stream.get("is_live", False)

        if is_live and self._config.get("live_on"):
            event_id = "live_on"
            if not seen("live", event_id):
                events.append(Event(type="live_on", text="Stream is now live", event_id=event_id))
                self._state.mark("live", event_id)
                log.info("Stream went live")

        if not is_live and self._config.get("live_off"):
            event_id = "live_off"
            if not seen("live", event_id):
                events.append(Event(type="live_off", text="Stream has gone offline", event_id=event_id))
                self._state.mark("live", event_id)
                log.info("Stream went offline")

        return events

    def run(self, callback: Callable[[Event], None]) -> None:
        """Block forever: poll, invoke callback for each event, sleep, repeat."""
        while True:
            events = self.poll()
            for event in events:
                log.info("Emitting event: type=%s text=%s", event.type, event.text)
                callback(event)
            time.sleep(self._config.get("poll_interval_seconds", 30))
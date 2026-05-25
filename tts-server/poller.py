"""RumblePoller — polls Rumble Live Stream API and extracts typed events."""

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

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
        """Fetch the latest update from the Rumble API via curl.

        Returns:
            List of Event objects. Empty list on any failure (network,
            malformed JSON, rate-limit, etc.) — never raises.
        """
        try:
            result = subprocess.run(
                [
                    "curl", "-s", "-A",
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "-G",
                    "--data-urlencode", f"key={self._api_key}",
                    self._api_url,
                ],
                capture_output=True,
                timeout=15,
            )
            if result.returncode != 0:
                log.warning("curl exited with %d", result.returncode)
                return []

            payload = json.loads(result.stdout)

        except json.JSONDecodeError as exc:
            log.warning("Malformed JSON from Rumble API: %s", exc)
            return []
        except Exception as exc:
            log.warning("Request failed: %s", exc)
            return []

        # Successful poll — reset backoff
        self._backoff = 0
        return self._extract_events(payload)

    def _extract_events(self, payload: dict) -> list[Event]:
        """Extract typed events from a Rumble API payload."""
        events: list[Event] = []
        seen = self._state.seen

        # --- latest_follower ---
        if self._config.get("new_follower") and "latest_follower" in payload.get("followers", {}):
            follower = payload["followers"]["latest_follower"]
            username = follower.get("username", "") if isinstance(follower, dict) else ""
            event_id = f"follower/{username}"
            if username and not seen("follower", username):
                events.append(Event(type="new_follower", text=f"New follower: {username}", event_id=event_id))
                self._state.mark("follower", username)
                log.info("New follower: %s", username)

        # --- subscribers ---
        if self._config.get("new_subscriber"):
            for sub in payload.get("subscribers", {}).get("recent_subscribers", []):
                username = sub.get("username", "") if isinstance(sub, dict) else ""
                amount = sub.get("amount", "") if isinstance(sub, dict) else ""
                event_id = f"subscriber/{username}"
                if username and not seen("subscriber", username):
                    text = f"New subscriber: {username}, {amount} dollars"
                    events.append(Event(type="new_subscriber", text=text, event_id=event_id))
                    self._state.mark("subscriber", username)
                    log.info("New subscriber: %s (%s)", username, amount)

        # --- gifted_subs ---
        if self._config.get("gifted_sub"):
            for gift in payload.get("gifted_subs", {}).get("recent_gifted_subs", []):
                purchased_by = gift.get("purchased_by", "") if isinstance(gift, dict) else ""
                event_id = f"gifted_sub/{purchased_by}"
                if purchased_by and not seen("gifted_sub", purchased_by):
                    text = f"Gifted sub from {purchased_by}"
                    events.append(Event(type="gifted_sub", text=text, event_id=event_id))
                    self._state.mark("gifted_sub", purchased_by)
                    log.info("Gifted sub from: %s", purchased_by)

        # --- chat_messages (from livestreams) ---
        if self._config.get("chat_message"):
            for stream in payload.get("livestreams", []):
                chat = stream.get("chat", {})
                for msg in chat.get("recent_messages", []):
                    username = msg.get("username", "") if isinstance(msg, dict) else ""
                    message = msg.get("text", "") if isinstance(msg, dict) else ""
                    event_id = f"chat/{username}/{message[:32]}"
                    if username and message and not seen("chat", event_id):
                        text = f"{username} said: {message}"
                        events.append(Event(type="chat_message", text=text, event_id=event_id))
                        self._state.mark("chat", event_id)
                        log.info("Chat: %s: %s", username, message[:50])

        # --- stream live state ---
        for stream in payload.get("livestreams", []):
            is_live = stream.get("is_live", False)
            event_id = f"live/{stream.get('id', 'unknown')}"

            if is_live and self._config.get("live_on"):
                if not seen("live", event_id):
                    events.append(Event(type="live_on", text="Stream is now live", event_id=event_id))
                    self._state.mark("live", event_id)
                    log.info("Stream went live")

            if not is_live and self._config.get("live_off"):
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
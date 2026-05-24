"""RumblePoller — polls Rumble Live Stream API and extracts typed events."""

import time
from dataclasses import dataclass
from typing import Callable

import requests


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

    def poll(self) -> list[Event]:
        """Fetch the latest update from the Rumble API.

        Returns:
            List of Event objects. Empty list on any failure (network,
            malformed JSON, etc.) — never raises.
        """
        try:
            response = requests.get(
                self._api_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=10,
            )
            payload = response.json()
        except Exception:
            return []

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

        # --- new_subscribers ---
        if self._config.get("new_subscriber") and "new_subscribers" in payload:
            for sub in payload["new_subscribers"]:
                username = sub.get("username", "")
                amount = sub.get("amount", "")
                event_id = f"subscriber/{username}"
                if username and not seen("subscriber", username):
                    events.append(Event(
                        type="new_subscriber",
                        text=f"New subscriber: {username}, {amount} dollars",
                        event_id=event_id,
                    ))
                    self._state.mark("subscriber", username)

        # --- gifted_subs ---
        if self._config.get("gifted_sub") and "gifted_subs" in payload:
            for gift in payload["gifted_subs"]:
                purchased_by = gift.get("purchased_by", "")
                event_id = f"gifted_sub/{purchased_by}"
                if purchased_by and not seen("gifted_sub", purchased_by):
                    events.append(Event(
                        type="gifted_sub",
                        text=f"Gifted sub from {purchased_by}",
                        event_id=event_id,
                    ))
                    self._state.mark("gifted_sub", purchased_by)

        # --- stream live state ---
        stream = payload.get("stream", {})
        is_live = stream.get("is_live", False)

        if is_live and self._config.get("live_on"):
            event_id = "live_on"
            if not seen("live", event_id):
                events.append(Event(type="live_on", text="Stream is now live", event_id=event_id))
                self._state.mark("live", event_id)

        # live_off is intentionally skipped when config is False (R3.9)

        # --- rant ---
        if self._config.get("rant") and "rant" in payload:
            rant = payload["rant"]
            username = rant.get("username", "")
            message = rant.get("message", "")
            event_id = f"rant/{username}"
            if username and not seen("rant", username):
                events.append(Event(
                    type="rant",
                    text=f"Rant: {username} said: {message}",
                    event_id=event_id,
                ))
                self._state.mark("rant", username)

        return events

    def run(self, callback: Callable[[Event], None]) -> None:
        """Block forever: poll, invoke callback for each event, sleep, repeat."""
        while True:
            events = self.poll()
            for event in events:
                callback(event)
            time.sleep(self._config["poll_interval_seconds"])
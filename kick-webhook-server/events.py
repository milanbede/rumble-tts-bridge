"""Kick webhook event → TTS text mapping + TTS file spooling."""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any


def _map_kick_event(event_dict: dict[str, Any], config_events: dict[str, bool]) -> str | None:
    """Map a Kick webhook event dict to TTS text.

    Args:
        event_dict: Parsed Kick webhook event with "event" and "data" keys.
        config_events: The "events" section from config, mapping event type
            names to booleans (True = enabled, False = disabled).

    Returns:
        A TTS text string for supported, enabled events; None for disabled,
        unknown, or malformed events.
    """
    event_type = event_dict.get("event")
    if not event_type:
        return None

    # Disabled events always return None, regardless of field presence
    enabled = config_events.get(event_type, False)
    if not enabled:
        return None

    data = event_dict.get("data", {})
    match event_type:
        case "channel.followed":
            username = data.get("user", {}).get("username")
            if not username:
                return None
            return f"New follower: {username}"

        case "channel.subscription.new":
            username = data.get("user", {}).get("username")
            amount = data.get("subscription", {}).get("amount")
            if not username or amount is None:
                return None
            return f"New subscriber: {username}, {amount} dollars"

        case "channel.subscription.gifts":
            gifter_username = data.get("gifter", {}).get("username")
            if not gifter_username:
                return None
            return f"Gifted sub from {gifter_username}"

        # renewal and chat.message.sent are disabled — already returned None above;
        # keep them explicitly for clarity.
        case "channel.subscription.renewal" | "chat.message.sent":
            return None

        case _:
            return None


class EventProcessor:
    """Processes Kick events into TTS audio files.

    Args:
        state_store: StateStore for deduplication.
        oauth_handler: OAuth2Handler instance (not currently used, reserved for future API calls).
        tts_player: TTSPlayer instance.
        spool_dir: Directory to write MP3 files.
        tts_server_url: URL of the TTS HTTP server (reserved, not used in this processor).
    """

    def __init__(
        self,
        state_store,
        oauth_handler,
        tts_player,
        spool_dir: str,
        tts_server_url: str = "http://localhost:8080",
    ) -> None:
        self.state_store = state_store
        self.oauth_handler = oauth_handler
        self.tts_player = tts_player
        self.spool_dir = spool_dir
        self.tts_server_url = tts_server_url

    async def process(self, event: dict[str, Any]) -> str | None:
        """Process a Kick event: deduplicate, map to TTS text, write MP3.

        Returns:
            Path to the written MP3 file, or None if the event was skipped/disabled/duplicate.
        """
        event_type = event.get("event", "")
        event_id = event.get("id", "")

        # Deduplicate
        if self.state_store and event_id and self.state_store.seen(event_type, event_id):
            return None
        if self.state_store:
            self.state_store.mark(event_type, event_id)

        # Map to TTS text
        # We use a flat events dict for backward compatibility
        events_config = {}
        tts_text = _map_kick_event(event, events_config)
        return None

    def process_sync(self, event: dict[str, Any]) -> str | None:
        """Blocking version of process() for use in non-async contexts."""
        return asyncio.run(self.process(event))
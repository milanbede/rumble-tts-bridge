"""Kick webhook event → TTS text mapping."""

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

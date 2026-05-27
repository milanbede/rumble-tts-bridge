"""Tests for kick-webhook-server event mapping."""

import pytest

from events import _map_kick_event


class TestMapKickEvent:
    """Tests for _map_kick_event()."""

    def test_unknown_event_type_returns_none(self):
        """Unknown event type → None."""
        event_dict = {"event": "channel.raid", "data": {}}
        config_events = {"channel.followed": True}
        assert _map_kick_event(event_dict, config_events) is None

    def test_channel_followed_returns_correct_text(self):
        """channel.followed → TTS text with username."""
        event_dict = {
            "event": "channel.followed",
            "data": {"user": {"id": 123, "username": "someuser"}},
        }
        config_events = {"channel.followed": True}
        assert _map_kick_event(event_dict, config_events) == "New follower: someuser"

    def test_channel_subscription_new_returns_correct_text(self):
        """channel.subscription.new → TTS text with username and amount."""
        event_dict = {
            "event": "channel.subscription.new",
            "data": {
                "user": {"id": 456, "username": "subscriber42"},
                "subscription": {"amount": 5},
            },
        }
        config_events = {"channel.subscription.new": True}
        assert _map_kick_event(event_dict, config_events) == "New subscriber: subscriber42, 5 dollars"

    def test_channel_subscription_gifts_returns_correct_text(self):
        """channel.subscription.gifts → TTS text with gifter username."""
        event_dict = {
            "event": "channel.subscription.gifts",
            "data": {"gifter": {"id": 789, "username": "generousfan"}},
        }
        config_events = {"channel.subscription.gifts": True}
        assert _map_kick_event(event_dict, config_events) == "Gifted sub from generousfan"

    def test_disabled_event_subscription_renewal_returns_none(self):
        """Disabled channel.subscription.renewal → None."""
        event_dict = {
            "event": "channel.subscription.renewal",
            "data": {"user": {"username": "reneweduser"}},
        }
        config_events = {"channel.subscription.renewal": False}
        assert _map_kick_event(event_dict, config_events) is None

    def test_disabled_event_chat_message_sent_returns_none(self):
        """Disabled chat.message.sent → None."""
        event_dict = {
            "event": "chat.message.sent",
            "data": {"user": {"username": "chatuser"}, "content": "hello"},
        }
        config_events = {"chat.message.sent": False}
        assert _map_kick_event(event_dict, config_events) is None

    def test_missing_fields_do_not_crash(self):
        """Missing fields return None instead of crashing."""
        # No "data" key at all
        assert _map_kick_event({"event": "channel.followed"}, {"channel.followed": True}) is None

        # No "user" inside data
        assert (
            _map_kick_event(
                {"event": "channel.followed", "data": {}},
                {"channel.followed": True},
            )
            is None
        )

        # No "username" inside user
        assert (
            _map_kick_event(
                {"event": "channel.followed", "data": {"user": {"id": 123}}},
                {"channel.followed": True},
            )
            is None
        )

        # channel.subscription.new — missing subscription
        assert (
            _map_kick_event(
                {"event": "channel.subscription.new", "data": {"user": {"username": "x"}}},
                {"channel.subscription.new": True},
            )
            is None
        )

        # channel.subscription.new — missing amount
        assert (
            _map_kick_event(
                {
                    "event": "channel.subscription.new",
                    "data": {"user": {"username": "x"}, "subscription": {}},
                },
                {"channel.subscription.new": True},
            )
            is None
        )

        # channel.subscription.gifts — no gifter
        assert (
            _map_kick_event(
                {"event": "channel.subscription.gifts", "data": {}},
                {"channel.subscription.gifts": True},
            )
            is None
        )

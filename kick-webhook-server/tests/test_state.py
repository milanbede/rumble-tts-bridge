"""Tests for kick-webhook-server StateStore (R2)."""

import json
import os
import tempfile

import pytest

from state import StateStore


@pytest.fixture
def store(tmp_path):
    """Fresh StateStore backed by a temp directory."""
    return StateStore(str(tmp_path))


class TestStateStore:
    def test_creates_state_json_if_not_exists(self, tmp_path):
        """StateStore creates state.json on init if it doesn't exist."""
        assert not (tmp_path / "state.json").exists()
        StateStore(str(tmp_path))
        assert (tmp_path / "state.json").exists()

    def test_seen_returns_false_for_new_id(self, store):
        """seen() returns False for an event_type/event_id pair never marked."""
        assert store.seen("followed", "u123") is False

    def test_mark_then_seen_returns_true(self, store):
        """After mark(), seen() returns True for that pair."""
        store.mark("followed", "u123")
        assert store.seen("followed", "u123") is True

    def test_different_event_types_independent(self, store):
        """Marking followed/u123 does NOT mark subscription/u123."""
        store.mark("followed", "u123")
        assert store.seen("followed", "u123") is True
        assert store.seen("subscription_new", "u123") is False

    def test_persistence_across_restarts(self, tmp_path):
        """seen() returns True for a marked pair after process restart."""
        store1 = StateStore(str(tmp_path))
        store1.mark("followed", "u456")
        del store1

        store2 = StateStore(str(tmp_path))
        assert store2.seen("followed", "u456") is True

    def test_multiple_event_ids_per_type(self, store):
        """Multiple event_ids can be marked under the same event_type."""
        store.mark("followed", "alice")
        store.mark("followed", "bob")
        store.mark("followed", "carol")
        assert store.seen("followed", "alice") is True
        assert store.seen("followed", "bob") is True
        assert store.seen("followed", "carol") is True
        assert store.seen("followed", "dave") is False

    def test_state_json_format(self, tmp_path):
        """state.json contains a dict with lists, not raw sets."""
        store = StateStore(str(tmp_path))
        store.mark("followed", "alice")
        store.mark("subscription_new", "bob")

        raw = json.loads((tmp_path / "state.json").read_text())
        assert isinstance(raw, dict)
        assert "followed" in raw
        assert "subscription_new" in raw
        assert isinstance(raw["followed"], list)
        assert "alice" in raw["followed"]
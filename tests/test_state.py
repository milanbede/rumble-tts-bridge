import os, tempfile, pytest, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tts-server'))
from state import StateStore

def test_seen_returns_false_for_new_event():
    with tempfile.TemporaryDirectory() as tmpdir:
        s = StateStore(tmpdir)
        assert s.seen("follower", "u123") is False

def test_seen_returns_true_after_mark():
    with tempfile.TemporaryDirectory() as tmpdir:
        s = StateStore(tmpdir)
        s.mark("follower", "u123")
        assert s.seen("follower", "u123") is True

def test_different_event_types_independent():
    with tempfile.TemporaryDirectory() as tmpdir:
        s = StateStore(tmpdir)
        s.mark("follower", "u123")
        assert s.seen("subscriber", "u123") is False

def test_persistence_across_restarts():
    with tempfile.TemporaryDirectory() as tmpdir:
        s1 = StateStore(tmpdir)
        s1.mark("follower", "u456")
        s2 = StateStore(tmpdir)
        assert s2.seen("follower", "u456") is True
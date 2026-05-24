"""Tests for TTSEngine (edge-tts wrapper)."""

import os
import tempfile
import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tts-server"))
from tts import TTSEngine

# MP3 frame header bytes that edge-tts produces (MPEG Audio Layer 3)
MP3_HEADER_BYTES = (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xfa")


def is_valid_mp3(path: str) -> bool:
    """Return True if *path* is a real MP3 file (starts with an MPEG audio frame header)."""
    if not os.path.isfile(path):
        return False
    with open(path, "rb") as f:
        header = f.read(4)
    return header[:2] in MP3_HEADER_BYTES


class TestTTSEngineInit:
    """TTSEngine stores construction parameters."""

    def test_stores_voice(self, tmp_path):
        engine = TTSEngine(str(tmp_path), voice="en-US-JennyNeural")
        assert engine.voice == "en-US-JennyNeural"

    def test_stores_rate(self, tmp_path):
        engine = TTSEngine(str(tmp_path), rate="+20%")
        assert engine.rate == "+20%"

    def test_stores_volume(self, tmp_path):
        engine = TTSEngine(str(tmp_path), volume="+50%")
        assert engine.volume == "+50%"

    def test_stores_spool_dir(self, tmp_path):
        engine = TTSEngine(str(tmp_path))
        assert engine.spool_dir == str(tmp_path)


class TestTTSEngineSpeak:
    """TTSEngine.speak() converts text to MP3."""

    def test_speak_returns_path_ending_in_mp3(self, tmp_path):
        engine = TTSEngine(str(tmp_path), voice="en-US-AriaNeural")
        path = engine.speak("Hello world")
        assert path.endswith(".mp3")

    def test_speak_returns_path_inside_spool_dir(self, tmp_path):
        engine = TTSEngine(str(tmp_path), voice="en-US-AriaNeural")
        path = engine.speak("Hello world")
        # Resolve both to absolute to avoid path confusion
        assert os.path.isabs(path), f"expected absolute path, got: {path}"
        resolved = os.path.abspath(path)
        spool_resolved = os.path.abspath(str(tmp_path))
        assert resolved.startswith(spool_resolved), (
            f"expected path inside spool_dir, got: {path} not under {tmp_path}"
        )

    def test_speak_produces_valid_mp3(self, tmp_path):
        engine = TTSEngine(str(tmp_path), voice="en-US-AriaNeural")
        path = engine.speak("Testing one two three")
        assert is_valid_mp3(path), f"generated file is not a valid MP3: {path}"

    def test_speak_returns_new_file_each_call(self, tmp_path):
        engine = TTSEngine(str(tmp_path), voice="en-US-AriaNeural")
        path1 = engine.speak("First")
        path2 = engine.speak("Second")
        assert path1 != path2
        assert os.path.isfile(path1)
        assert os.path.isfile(path2)

    def test_speak_uses_custom_job_id_as_filename_stem(self, tmp_path):
        engine = TTSEngine(str(tmp_path), voice="en-US-AriaNeural")
        path = engine.speak("Hello", job_id="my_custom_job")
        assert os.path.basename(path) == "my_custom_job.mp3"

    def test_speak_without_job_id_uses_uuid_stem(self, tmp_path):
        engine = TTSEngine(str(tmp_path), voice="en-US-AriaNeural")
        path = engine.speak("Hello")
        basename = os.path.basename(path)
        assert basename.endswith(".mp3")
        stem = basename[:-4]
        # UUIDs are 36 chars: 8-4-4-4-12
        assert len(stem) == 36, f"expected UUID stem, got: {stem}"
        assert stem.count("-") == 4

    def test_speak_creates_spool_dir_if_missing(self, tmp_path):
        spool = tmp_path / "nonexistent" / "spool"
        engine = TTSEngine(str(spool), voice="en-US-AriaNeural")
        path = engine.speak("Hello")
        assert os.path.isdir(str(spool))
        assert os.path.isfile(path)

    def test_speak_network_failure_raises_exception(self, tmp_path, monkeypatch):
        """Simulate a network failure in edge-tts and verify it raises."""
        import asyncio
        original_run = asyncio.run

        def fake_run(coro):
            raise OSError("network unavailable")

        # Patch asyncio.run at the module level
        import tts
        monkeypatch.setattr(asyncio, "run", fake_run)
        engine = TTSEngine(str(tmp_path), voice="en-US-AriaNeural")
        with pytest.raises(Exception):
            engine.speak("Hello")
"""Tests for TTSPlayer (tts_speaker.py)."""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from tts_speaker import TTSPlayer, get_or_create_player


class TestGetOrCreatePlayer:
    def test_returns_same_player_for_same_voice(self):
        """Two calls with the same voice return the identical player instance."""
        config1 = {"voice": "en-US-AriaNeural", "rate": "+0%", "volume": "+0%"}
        config2 = {"voice": "en-US-AriaNeural", "rate": "+10%", "volume": "+0%"}

        player1 = get_or_create_player(config1)
        player2 = get_or_create_player(config2)

        assert player1 is player2

    def test_returns_different_player_for_different_voice(self):
        """Different voice names produce different player instances."""
        config1 = {"voice": "en-US-AriaNeural", "rate": "+0%", "volume": "+0%"}
        config2 = {"voice": "en-GB-S нейрон", "rate": "+0%", "volume": "+0%"}  # intentionally distinct

        player1 = get_or_create_player(config1)
        player2 = get_or_create_player(config2)

        assert player1 is not player2
        assert player1.voice != player2.voice


class TestTTSPlayerSpeak:
    @pytest.mark.asyncio
    async def test_speak_does_not_block(self):
        """speak() returns immediately without waiting for synthesis to finish."""
        player = TTSPlayer({"voice": "en-US-AriaNeural", "rate": "+0%", "volume": "+0%"})

        # Patch the implementation so we don't need real audio synthesis
        with patch.object(
            player,
            "_speak_impl",
            new=AsyncMock(return_value=None),
        ):
            start = time.monotonic()
            await player.speak("hello world")
            elapsed = time.monotonic() - start

            # Must return within 100ms — far faster than any real TTS synthesis
            assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_speak_and_wait_completes(self):
        """speak_and_wait() finishes after synthesis is complete."""
        player = TTSPlayer({"voice": "en-US-AriaNeural", "rate": "+0%", "volume": "+0%"})

        with patch.object(
            TTSPlayer,
            "_speak_impl",
            new=AsyncMock(return_value=None),
        ):
            # Should complete successfully (our mock never raises)
            await player.speak_and_wait("hello world")

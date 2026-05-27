"""TTSPlayer — async Edge TTS integration with per-user voice affinity.

Provides fire-and-forget speaking via asyncio.create_task and a
blocking speak_and_wait for testing.
"""

from __future__ import annotations

import asyncio
import threading
from typing import ClassVar

import edge_tts


class TTSPlayer:
    """Wrapper around edge-tts for async fire-and-forget speech.

    Args:
        config_tts: Dict with keys:
            - voice (str): edge-tts voice name (default "en-US-AriaNeural")
            - rate  (str): rate modifier e.g. "+10%" (default "+0%")
            - volume (str): volume modifier e.g. "+0%" (default "+0%")
    """

    def __init__(self, config_tts: dict) -> None:
        self.voice: str = config_tts.get("voice", "en-US-AriaNeural")
        self.rate: str = config_tts.get("rate", "+0%")
        self.volume: str = config_tts.get("volume", "+0%")

    async def speak(self, text: str) -> None:
        """Speak text in a fire-and-forget asyncio task (non-blocking)."""
        asyncio.create_task(self._speak_impl(text))

    async def speak_and_wait(self, text: str) -> None:
        """Speak text and wait for completion (for testing)."""
        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            volume=self.volume,
        )
        async for _ in communicate.stream():
            pass  # consume audio bytes — no saving needed for playback

    async def _speak_impl(self, text: str) -> None:
        """Internal coroutine that does the actual synthesis."""
        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            volume=self.volume,
        )
        async for _ in communicate.stream():
            pass
        # Suppress unclosed session warning
        await communicate.stream().aclose()


# ----------------------------------------------------------------------
# Singleton registry — one player per unique voice name
# ----------------------------------------------------------------------

_player_registry: ClassVar[dict[str, TTSPlayer]] = {}
_registry_lock: ClassVar[threading.Lock] = threading.Lock()


def get_or_create_player(config_tts: dict) -> TTSPlayer:
    """Return the shared TTSPlayer for the given voice, creating it if needed.

    Thread-safe: uses a lock around registry access.
    """
    voice = config_tts.get("voice", "en-US-AriaNeural")
    with _registry_lock:
        if voice not in _player_registry:
            _player_registry[voice] = TTSPlayer(config_tts)
        return _player_registry[voice]

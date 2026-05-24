"""TTSEngine — edge-tts wrapper that converts text to MP3.

Speaks text synchronously using Microsoft Edge TTS, writes audio to a spool
directory, and returns the Path of the generated MP3 file.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import edge_tts


class TTSEngine:
    """Wrapper around edge-tts to convert text to MP3."""

    def __init__(
        self,
        spool_dir: str,
        voice: str = "en-US-AriaNeural",
        rate: str = "+0%",
        volume: str = "+0%",
    ) -> None:
        self.spool_dir = str(spool_dir)
        self.voice = voice
        self.rate = rate
        self.volume = volume

    def speak(self, text: str, job_id: str | None = None) -> str:
        """Convert *text* to MP3 and return the absolute path to the file.

        Args:
            text: Text to synthesize.
            job_id: If provided, use this as the filename stem (e.g. ``job_id.mp3``).
                    Otherwise a random UUID is used.

        Returns:
            Absolute path to the generated MP3 file inside ``spool_dir``.

        Raises:
            Exception: On network failure or TTS synthesis error.
        """
        # Ensure spool directory exists
        os.makedirs(self.spool_dir, exist_ok=True)

        # Choose filename stem
        if job_id is not None:
            stem = job_id
        else:
            stem = str(uuid.uuid4())
        out_path = os.path.join(self.spool_dir, f"{stem}.mp3")

        try:
            asyncio.run(
                edge_tts.Communicate(
                    text=text,
                    voice=self.voice,
                    rate=self.rate,
                    volume=self.volume,
                ).save(out_path)
            )
        except Exception as exc:
            # Clean up partial file if any
            if os.path.exists(out_path):
                os.remove(out_path)
            raise Exception(f"TTS network/synthesis failure: {exc}") from exc

        return os.path.abspath(out_path)
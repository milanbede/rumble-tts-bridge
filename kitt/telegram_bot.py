"""
Telegram bot for KITT profile — voice in / TTS voice out.

Receives voice messages, transcribes via OpenAI Whisper,
forwards text to Hermes profile (via HTTP to the gateway),
generates KITT TTS via edge-tts, dual-path delivers:
  1. sends audio to Telegram
  2. writes MP3 to spool directory for Pi Zero playback

Bot runs long-polling (no webhook) for simplicity.

Also runs an HTTP API server (default port 8082) that exposes:
  POST /send-audio  — used by tts-server to send TTS audio via this bot's
                      Telegram token (resolves the token-conflict issue).

Architecture:
  - Telegram long-polling runs in a daemon thread (python-telegram-bot)
  - HTTP API server runs in the main thread (stdlib http.server)
  - Both share the same Telegram bot token and chat_id config
"""

from __future__ import annotations

import http.server
import json
import logging
import os
import tempfile
import threading
import uuid
from pathlib import Path

import asyncio
import edge_tts
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ── Config ───────────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.environ.get(
    "KITT_TELEGRAM_BOT_TOKEN",
    "8913561503:AAEbGmG4HMz9hZG3jUvZ_yLZNVwCh2qETZk",  # TODO: replace with real token
)
TELEGRAM_CHAT_ID = os.environ.get("KITT_TELEGRAM_CHAT_ID", "7292599600")

# Hermes gateway — where the KITT profile listens for messages
HERMES_GATEWAY_URL = os.environ.get(
    "KITT_HERMES_GATEWAY_URL", "http://localhost:9119"
)

# Spool directory for Pi Zero polling
SPOOL_DIR = Path(os.environ.get("KITT_SPOOL_DIR", str(Path.home() / "KITT" / "spool")))

# Voice for KITT (deep, robotic — KITT voice)
KITT_VOICE = os.environ.get("KITT_VOICE", "en-US-JasperNeural")
KITT_RATE = os.environ.get("KITT_RATE", "+0%")
KITT_VOLUME = os.environ.get("KITT_VOLUME", "+0%")

# Whisper model size — "base" is a good balance of speed/accuracy for local use
WHISPER_MODEL = os.environ.get("KITT_WHISPER_MODEL", "base")

# HTTP API server port (for /send-audio endpoint used by tts-server)
HTTP_API_PORT = int(os.environ.get("KITT_HTTP_API_PORT", "8082"))

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ── STT: OpenAI Whisper ───────────────────────────────────────────────────────

def load_whisper():
    """Lazily import and cached whisper load."""
    import whisper
    return whisper


def transcribe_audio(audio_path: str) -> str:
    """Transcribe an audio file to text using OpenAI Whisper.

    Args:
        audio_path: Path to the audio file (mp3, ogg, m4a, etc.)

    Returns:
        Transcribed text string.

    Raises:
        Exception: On model load or transcription failure.
    """
    try:
        model = load_whisper().load_model(WHISPER_MODEL)
        result = model.transcribe(audio_path, fp16=False)
        return result["text"].strip()
    except Exception as exc:
        raise Exception(f"Whisper transcription failed: {exc}") from exc


# ── TTS: KITT voice via edge-tts ─────────────────────────────────────────────

async def _generate_tts(text: str, output_path: str) -> str:
    """Generate KITT TTS MP3 using edge-tts (async).

    Args:
        text: Text to synthesize.
        output_path: Destination .mp3 path.

    Returns:
        Absolute path to the MP3 file.
    """
    await edge_tts.Communicate(
        text=text,
        voice=KITT_VOICE,
        rate=KITT_RATE,
        volume=KITT_VOLUME,
    ).save(output_path)
    return os.path.abspath(output_path)


def speak_kitt(text: str, job_id: str | None = None) -> str:
    """Synchronous KITT TTS generation.

    Args:
        text: Text to synthesize.
        job_id: Filename stem. Defaults to UUID.

    Returns:
        Absolute path to the generated MP3.
    """
    os.makedirs(SPOOL_DIR, exist_ok=True)
    stem = job_id or str(uuid.uuid4())
    out_path = os.path.join(SPOOL_DIR, f"{stem}.mp3")

    try:
        asyncio.run(_generate_tts(text, out_path))
    except Exception as exc:
        if os.path.exists(out_path):
            os.remove(out_path)
        raise Exception(f"KITT TTS generation failed: {exc}") from exc

    return os.path.abspath(out_path)


# ── Hermes profile forwarding ─────────────────────────────────────────────────

def forward_to_hermes(text: str) -> str | None:
    """Forward transcribed text to the KITT Hermes profile and return its response.

    Currently hits the local dashboard; in production this would be the
    KITT profile's DM endpoint (e.g. Telegram webhook or Hermes gateway
    profile-invoke endpoint).

    Returns:
        The profile's text response, or None if the gateway is unreachable.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    try:
        payload = urllib.parse.urlencode({"text": text}).encode()
        req = urllib.request.Request(
            f"{HERMES_GATEWAY_URL}/profile/kitt/",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 200:
                return resp.read().decode("utf-8")
    except urllib.error.URLError:
        logger.warning("Hermes gateway unreachable — responding with TTS only")
    except Exception as exc:
        logger.error(f"Hermes forwarding error: {exc}")

    return None


# ── Dual-path delivery ────────────────────────────────────────────────────────

def deliver_dual(mp3_path: str, context: str = "") -> None:
    """Write MP3 to spool for Pi Zero; Telegram sending handled by caller.

    Args:
        mp3_path: Absolute path to the generated MP3.
        context: Description for logging.
    """
    os.makedirs(SPOOL_DIR, exist_ok=True)
    logger.info(f"[KITT spool] {context} → {mp3_path}")


# ── Telegram helpers (shared with HTTP API) ───────────────────────────────────

async def _send_audio_via_telegram(chat_id: str, audio_path: str, caption: str = "") -> None:
    """Send an MP3 file to a Telegram chat.

    Used by both the bot's own handlers and the /send-audio HTTP endpoint.

    Args:
        chat_id: Target Telegram chat ID.
        audio_path: Path to the MP3 file.
        caption: Optional text caption.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    token = TELEGRAM_BOT_TOKEN
    base_url = f"https://api.telegram.org/bot{token}"

    with open(audio_path, "rb") as audio_f:
        audio_data = audio_f.read()

    boundary = "----FormBoundary7h2k9s8d"
    body_parts: list[bytes] = [
        (f"--{boundary}\r\n"
         f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n').encode(),
    ]
    if caption:
        body_parts.append(
            (f"--{boundary}\r\n"
             f'Content-Disposition: form-data; name="caption"\r\n\r\n'
             f"{caption}\r\n").encode()
        )
    body_parts.extend([
        (f"--{boundary}\r\n"
         f'Content-Disposition: form-data; name="audio"; filename="{Path(audio_path).name}"\r\n'
         f"Content-Type: audio/mpeg\r\n\r\n").encode(),
        audio_data,
        f"\r\n--{boundary}--\r\n".encode(),
    ])

    req = urllib.request.Request(
        f"{base_url}/sendAudio",
        data=b"".join(body_parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise Exception(f"sendAudio returned {resp.status}")


def send_audio_to_telegram_sync(chat_id: str, audio_path: str, caption: str = "") -> None:
    """Synchronous wrapper around _send_audio_via_telegram for use in HTTP handlers.

    Creates a new asyncio event loop per call since the HTTP server runs
    in the main thread (not async).
    """
    asyncio.run(_send_audio_via_telegram(chat_id, audio_path, caption))


# ── HTTP API Server ───────────────────────────────────────────────────────────
# Serves /send-audio for tts-server → KITT bot integration.
# Runs in the main thread; Telegram polling runs in a daemon thread.

class _HTTPAPIHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for the KITT bot HTTP API."""

    # Class-level refs set by _make_http_handler
    bot_chat_id: str = ""

    def do_POST(self):
        if self.path == "/send-audio":
            self._handle_send_audio()
        else:
            self._send_json(404, {"error": "Not found"})

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "Not found"})

    def _handle_send_audio(self):
        """Receive an MP3 file and send it to the configured Telegram chat.

        Content-Type: audio/mpeg (raw MP3 bytes), or multipart/form-data.
        Optional caption via X-Caption header or form field.

        Returns 200 on success, 500 on failure.
        """
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json(400, {"error": "Missing request body"})
            return

        ct = self.headers.get("Content-Type", "")
        caption = self.headers.get("X-Caption", "") or ""

        # Read body
        try:
            body = self.rfile.read(content_length)
        except Exception as exc:
            self._send_json(400, {"error": f"Could not read body: {exc}"})
            return

        # Write to temp file
        temp_dir = tempfile.mkdtemp(prefix="kitt_http_audio_")
        audio_path = os.path.join(temp_dir, f"{uuid.uuid4().hex[:8]}.mp3")
        try:
            with open(audio_path, "wb") as f:
                f.write(body)

            send_audio_to_telegram_sync(self.bot_chat_id, audio_path, caption=caption)
            logger.info(f"[/send-audio] sent {len(body)} bytes to Telegram chat {self.bot_chat_id}")
            self._send_json(200, {"ok": True})
        except Exception as exc:
            logger.error(f"[/send-audio] error: {exc}")
            self._send_json(500, {"error": str(exc)})
        finally:
            try:
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    def _send_json(self, code: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args):
        """Suppress default request logging."""
        pass


def _make_http_handler(chat_id: str):
    """Return a _HTTPAPIHandler class bound to bot_chat_id."""
    class H(_HTTPAPIHandler):
        pass
    H.bot_chat_id = chat_id
    return H


def run_http_api(port: int, chat_id: str):
    """Run the HTTP API server (blocks — call in main thread)."""
    handler = _make_http_handler(chat_id)
    server = http.server.HTTPServer(("0.0.0.0", port), handler)
    logger.info(f"[/send-audio] HTTP API server listening on port {port}")
    server.serve_forever()


# ── Telegram handlers ──────────────────────────────────────────────────────────

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Receive a voice message, transcribe it, process with LLM, respond with KITT TTS."""
    logger.info(f"Voice message from {update.effective_user.first_name} in chat {update.effective_chat.id}")

    voice = update.message.voice
    file_size_mb = voice.file_size / (1024 * 1024)
    logger.info(f"  Voice file size: {file_size_mb:.1f} MB")

    sent_msg = await update.message.reply_text("🎤 Processing your voice message...")

    import shutil
    temp_dir = None
    try:
        bot_file = await context.bot.get_file(voice.file_id)
        temp_dir = tempfile.mkdtemp(prefix="kitt_voice_")
        ogg_path = os.path.join(temp_dir, f"{voice.file_id}.ogg")
        await bot_file.download_to_drive(ogg_path)
        logger.info(f"  Downloaded to {ogg_path}")

        await context.bot.edit_message_text(
            "🗣️ Transcribing...",
            chat_id=update.effective_chat.id,
            message_id=sent_msg.message_id,
        )
        transcribed = transcribe_audio(ogg_path)
        if not transcribed:
            await context.bot.edit_message_text(
                "❓ Could not understand the audio. Please try again.",
                chat_id=update.effective_chat.id,
                message_id=sent_msg.message_id,
            )
            return
        logger.info(f"  Transcribed: {transcribed[:80]}{'...' if len(transcribed) > 80 else ''}")

        await context.bot.edit_message_text(
            "🤖 Thinking...",
            chat_id=update.effective_chat.id,
            message_id=sent_msg.message_id,
        )
        profile_response = forward_to_hermes(transcribed)
        response_text = profile_response if profile_response else f"You said: {transcribed}"
        logger.info(f"  KITT response: {response_text[:80]}{'...' if len(response_text) > 80 else ''}")

        await context.bot.edit_message_text(
            "🔊 Generating KITT voice response...",
            chat_id=update.effective_chat.id,
            message_id=sent_msg.message_id,
        )
        job_id = f"kitt_{uuid.uuid4().hex[:8]}"
        mp3_path = speak_kitt(response_text, job_id=job_id)
        logger.info(f"  TTS generated: {mp3_path}")

        with open(mp3_path, "rb") as audio_f:
            await context.bot.send_audio(
                chat_id=update.effective_chat.id,
                audio=audio_f,
                title=f"KITT — {job_id}",
                performer="KITT",
            )
        logger.info(f"  Sent to Telegram chat {update.effective_chat.id}")
        deliver_dual(mp3_path, context=f"response:{job_id}")

        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=sent_msg.message_id,
        )

    except Exception as exc:
        logger.error(f"handle_voice error: {exc}", exc_info=True)
        try:
            await context.bot.edit_message_text(
                f"❌ Error processing voice: {exc}",
                chat_id=update.effective_chat.id,
                message_id=sent_msg.message_id,
            )
        except Exception:
            pass
    finally:
        if temp_dir:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Receive a text message, process with LLM, respond with KITT TTS."""
    logger.info(f"Text message from {update.effective_user.first_name}: {update.message.text[:80]}")

    try:
        profile_response = forward_to_hermes(update.message.text)
        response_text = profile_response if profile_response else update.message.text

        job_id = f"kitt_{uuid.uuid4().hex[:8]}"
        mp3_path = speak_kitt(response_text, job_id=job_id)

        with open(mp3_path, "rb") as audio_f:
            await context.bot.send_audio(
                chat_id=update.effective_chat.id,
                audio=audio_f,
                title=f"KITT — {job_id}",
                performer="KITT",
            )
        deliver_dual(mp3_path, context=f"response:{job_id}")

    except Exception as exc:
        logger.error(f"handle_text error: {exc}", exc_info=True)
        await update.message.reply_text(f"❌ Error: {exc}")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 KITT is online.\n\n"
        "Send me a voice message or text — I'll respond with KITT TTS.\n"
        "Audio also plays on the Pi Zero via spool.\n\n"
        "Commands:\n"
        "/start — show this message\n"
        "/kitt — same as /start"
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    """Build and run both the Telegram bot (threaded) and HTTP API server (main)."""
    logger.info("Starting KITT Telegram bot + HTTP API...")

    # Start Telegram polling in a daemon thread
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler(["start", "kitt"], cmd_start))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    telegram_thread = threading.Thread(
        target=app.run_polling,
        kwargs={"drop_pending_updates": True},
        daemon=True,
        name="telegram-polling",
    )
    telegram_thread.start()
    logger.info(
        f"Telegram polling started — token prefix: {TELEGRAM_BOT_TOKEN[:10]}..."
    )
    logger.info(f"Spool directory: {SPOOL_DIR}")
    logger.info(f"Hermes gateway: {HERMES_GATEWAY_URL}")

    # HTTP API server runs in main thread (serves /send-audio for tts-server)
    run_http_api(HTTP_API_PORT, TELEGRAM_CHAT_ID)


if __name__ == "__main__":
    main()

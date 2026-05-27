# KITT TTS Workflow

> Skill for KITT voice output — dual-path TTS via edge-tts to Telegram + Pi Zero spool.

## Overview

KITT uses Microsoft Edge TTS (edge-tts) to generate audio responses. Audio is delivered via two paths:
1. **Telegram** — audio sent directly via bot API
2. **Pi Zero spool** — MP3 written to `~/KITT/spool/` for the `pi-client` to poll and play

## Voice Configuration

KITT's voice is configured via environment variables:

```bash
KITT_VOICE="en-US-JasperNeural"   # deep, authoritative male voice
KITT_RATE="+0%"
KITT_VOLUME="+0%"
```

Or hardcoded defaults in `telegram_bot.py`:
```python
KITT_VOICE = "en-US-JasperNeural"  # deep robotic voice
```

## Supported Voices

The `en-US-JasperNeural` voice is the primary KITT voice. Other options:
- `en-US-GuyNeural` — clear male
- `en-US-AriaNeural` — female, lighter tone
- `en-GB-RyanNeural` — UK male, more robotic edge

## Usage

```python
from kitt.telegram_bot import speak_kitt

mp3_path = speak_kitt("KITT online and ready.")
# Returns: /Users/milan-bede/KITT/spool/<uuid>.mp3
```

## Dual-Path Delivery

```python
from kitt.telegram_bot import speak_kitt, deliver_dual

job_id = "kitt_abc123"
mp3_path = speak_kitt("Alert triggered.", job_id=job_id)

# Telegram: handled by caller (e.g. handle_voice, handle_text)
# Spool: pi-client polls ~/KITT/spool/
deliver_dual(mp3_path, context=f"response:{job_id}")
```

## HTTP API: /send-audio

tts-server uses this endpoint to route Telegram announcements through the KITT bot
(instead of holding its own Telegram token — which was the token conflict):

```bash
POST http://127.0.0.1:8082/send-audio
Content-Type: audio/mpeg
X-Caption: New subscriber alert!

<raw MP3 bytes>
```

The KITT bot holds the ONE Telegram bot token and runs the single long-polling loop.

## Spool Path

`~/KITT/spool/` — monitored by `pi-client` on the Pi Zero. Files are named:
- `kitt_<short_uuid>.mp3` — KITT responses (from telegram_bot.py)
- `<job_id>.mp3` — event-triggered TTS (from tts-server/server.py via /send-audio)

## Connection to Voice Input

The `kitt-voice-input` skill handles the inbound voice path:
- Telegram voice message → Whisper STT → Hermes profile → KITT TTS → dual-path delivery

The TTS engine here is the same one used by `kitt/telegram_bot.py` (edge-tts with `en-US-JasperNeural`).

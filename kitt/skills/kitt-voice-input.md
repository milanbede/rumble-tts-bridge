---
name: kitt-voice-input
description: Receive voice messages via Telegram bot, transcribe with Whisper STT, forward text to LLM for KITT profile processing.
version: 1.0.0
metadata:
  hermes:
    tags: [kitt, voice, stt, telegram, whisper]
    requires: [python-telegram-bot, openai-whisper]
---

# KITT Voice Input Skill

Receive voice messages from Telegram, transcribe to text, and prepare for KITT LLM processing.

## Overview

The KITT Telegram bot (`kitt/telegram_bot.py`) handles:
1. **Voice message receipt** via python-telegram-bot long-polling
2. **STT transcription** via OpenAI Whisper (`base` model by default)
3. **Text forwarding** to the KITT Hermes profile via gateway HTTP POST
4. **Response handling** — profile returns text, KITT TTS generates audio

## Voice Processing Flow

```
[Telegram Voice Message]
        │
        ▼
[Download .ogg via bot API]  → temp file
        │
        ▼
[Whisper base model transcribe] → text
        │
        ▼
[POST to Hermes gateway /profile/kitt] → response text
        │
        ▼
[KITT TTS via edge-tts] → MP3
        │
        ├──▶ [Send audio to Telegram chat]
        └──▶ [Write to spool for Pi Zero]
```

## Bot Startup

```bash
cd ~/KITT/kitt
python3 telegram_bot.py
```

Environment variables:
- `KITT_TELEGRAM_BOT_TOKEN` — Telegram bot token
- `KITT_TELEGRAM_CHAT_ID` — Target chat ID (default: 7292599600)
- `KITT_HTTP_API_PORT` — HTTP API port for /send-audio (default: 8082)
- `KITT_SPOOL_DIR` — Spool directory (default: ~/KITT/spool/)
- `KITT_HERMES_GATEWAY_URL` — Hermes gateway URL (default: http://localhost:9119)
- `KITT_WHISPER_MODEL` — Whisper model size (default: base)

## HTTP API Server

The bot also runs an HTTP API server (default port 8082) with:

- `POST /send-audio` — receives MP3 bytes, sends to Telegram. Used by tts-server to route announcements through the KITT bot (resolves token conflict). Send raw MP3 bytes with `Content-Type: audio/mpeg`, or `multipart/form-data`. Optional caption via `X-Caption` header.
- `GET /health` — returns `{"status": "ok"}`

Example from tts-server:
```bash
curl -X POST http://127.0.0.1:8082/send-audio \
  -H "Content-Type: audio/mpeg" \
  --data-binary @announce.mp3
```

## STT: Whisper Model Options

| Model  | Size  | Speed   | Accuracy |
|--------|-------|---------|----------|
| tiny   | ~75 MB | fastest | decent   |
| base   | ~140 MB | fast    | good     |
| small  | ~500 MB | medium  | very good |
| medium | ~1.5 GB | slow    | excellent |

Default: `base` — good balance for real-time use on MacBook.

First run downloads the model to `~/.cache/whisper/`.

## Voice Message Handling

The bot processes:
- **Voice messages** (`.ogg` via Telegram) → transcribed and processed
- **Text messages** → forwarded to profile directly
- **`/start` and `/kitt` commands** → info message

## Error Handling

- **Whisper fails**: reply "Could not understand the audio" to Telegram
- **Hermes gateway unreachable**: fallback to echoing the transcribed text with KITT flair
- **TTS fails**: log error, reply "Error generating voice" to Telegram
- **Temp file cleanup**: always runs in `finally` block after processing

## Testing

```bash
cd ~/KITT/kitt
python3 -m pytest tests/test_telegram_bot.py -v
```

Key test coverage:
- Whisper transcription success/failure
- TTS generation with cleanup on error
- Hermes forwarding (success, unreachable, non-200)
- Text message handler full flow
- `/start` command response
- `/send-audio` HTTP endpoint

## Spool Path

Audio files written to `~/KITT/spool/` for Pi Zero polling. Filename format: `kitt_<short_uuid>.mp3`

The `pi-client` on the Pi Zero polls this directory and plays new files over Bluetooth.

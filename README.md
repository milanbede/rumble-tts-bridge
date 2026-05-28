# KITT

> Smart bike TTS assistant. Telegram → Hermes `kitt` profile → TTS spoken over Bluetooth speaker on the RPI. Also announces Kick live chat, subs, and donations.

## Hardware

- **Raspberry Pi Zero 2W** — Tailscale IP: `100.89.216.54`, user: `milan-bede`
- **MacBook** — Tailscale IP: `100.96.5.8`
- **Bluetooth Speaker** — paired to RPI

## Architecture

```
[Telegram] ──► [kitt profile (MacBook)] ──► [LLM]
                                        │
                              ┌──────────┴──────────┐
                              ▼                     ▼
                     [kitt-watcher.py]        [SSH + mpc]
                      publishes /say              │
                              ▼                     ▼
                    [mosquitto (RPI)]         [MPD]
                              │
                     ┌───────┴───────┐
                     ▼               ▼
              [tts-player.py]  [kick-watcher.py]
              (edge-tts)          (KickApi)
              mpc ducking
                     │
                     ▼
              [Bluetooth Speaker]
```

**MQTT topic `/say` is the unified bus.** Both `kitt-watcher` (assistant responses) and `kick-watcher` (chat/sub/donation events) publish here. `tts-player.py` subscribes and speaks everything in order.

## Components

### RPI — tts-player.py

MQTT subscriber that renders text-to-speech and plays it. Subscribes to `/say` on the local mosquitto broker. Uses `edge-tts` for rendering, `mpc` for music ducking, and plays through the Bluetooth speaker.

### RPI — kick-watcher.py

Polls the Kick live chat API via `KickApi`. Detects chat messages, new subscribers, and donations. Publishes formatted TTS strings to the local mosquitto broker on `/say`.

### MacBook — kitt-watcher.py

Reads the `kitt` profile's `state.db` (assistant responses only, read-only). Publishes new responses to the RPI's mosquitto broker on `/say`.

### MacBook — Hermes `kitt` profile

Standard Hermes profile with Telegram integration, minimax-m2.7 model. SSH default remote set to RPI.

## Requirements

- mosquitto running on RPI (port 1883)
- `edge-tts` installed on RPI
- `mpc` installed on RPI
- MPD running as a service on RPI
- `paho-mqtt` installed on RPI (Python MQTT client)
- `KickApi` installed on RPI
- Bluetooth speaker paired to RPI

## Repo

https://github.com/milanbede/kitt
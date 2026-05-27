# KITT

> KITT is a Hermes profile — personal streaming DJ, music controller, and TTS announcement system. Chat with it on Telegram to control the Pi music player, hear replies via TTS, and get Kick stream alerts announced over the Pi speaker.

## Status

🟡 Planning — `kitt` profile spec complete — implementation not started (kanban: `rumble-tts` board)

**Sub-projects:**
- `tts-server` — ✅ Running (Rumble polling)
- `kick-webhook-server` — 🟡 In progress (Kick webhooks)
- `kitt` profile — 🔴 Planning (this spec)

---

## Quick Start (kitt profile)

```bash
# Chat with KITT on Telegram — it controls music + responds with TTS
# Profile: ~/.hermes/profiles/kitt/
```

---

## Architecture

```
[Telegram DM] ──► [kitt profile] ──► [LLM]
                                    │
                        ┌───────────┴───────────┐
                        │                       │
                   [TTS reply]            [music control]
                        │                       │
                ┌───────▼───────┐         [SSH to Pi]
                ▼               ▼         [mpc commands]
         [send_message]    [spool/]         [mpd]
         [Telegram audio]  [Pi plays]
```

**Audio paths (separate):**
- `spool/` — TTS only: agent Telegram replies + Kick webhook announcements → `pi-client` on Pi
- `music/` — separate: controlled via `mpc` on Pi, no spool involvement

## Status

🟡 Implementation underway — `kick-webhook-server` (kanban: `rumble-tts` board)

🔴 Planning complete — `pi-client` implementation not started.

## Architecture

```
[Rumble API] ──► [MacBook: tts-server :8080] ──► [spool/]
[Kick webhooks] ──► [MacBook: kick-webhook-server :8081] ──► [spool/]
                                                        │
                                          [Pi Zero 2 W: pull + play]
                                                        │
                              [BT A2DP: phone] ──► [speaker + TTS]
```

## Components

### tts-server (MacBook)

Polls Rumble Live Stream API, generates TTS MP3s via edge-tts, serves them over HTTP.

| File | Purpose |
|------|---------|
| `config.example.yaml` | Config template |
| `requirements.txt` | Python deps |
| `main.py` | Entry point |
| `poller.py` | Rumble API polling + event extraction |
| `tts.py` | edge-tts wrapper |
| `server.py` | HTTP server (spool + ACK) |
| `state.py` | Dedup state store |

### kick-webhook-server (MacBook)

Receives inbound Kick webhooks, generates TTS MP3s via edge-tts, serves them to Pi Zero. Shares the same spool directory as `tts-server`.

| File | Purpose |
|------|---------|
| `config.example.yaml` | Config template |
| `requirements.txt` | Python deps |
| `main.py` | Entry point |
| `webhook.py` | Flask server — POST /webhook, GET /health |
| `signature.py` | ECDSA secp256k1 signature verification |
| `events.py` | Kick event → TTS text mapping |
| `oauth.py` | OAuth2 token management |
| `state.py` | Dedup state store (copied from tts-server) |

### pi-client (Pi Zero 2 W)

Polls MacBook HTTP server, plays MP3s, ACKs deletion, bridges BT audio.

| File | Purpose |
|------|---------|
| `config.example.yaml` | Config template |
| `requirements.txt` | Python deps |
| `main.py` | Entry point |
| `player.py` | TTSPlayer: poll + download + play + ACK |
| `bt-bridge.sh` | BT pairing + bluez-alsa A2DP bridge |

## Setup

### MacBook

```bash
cd tts-server
cp config.example.yaml config.yaml
# add your RUMBLE_API_KEY — https://rumble.com/account/livestream-api
pip install -r requirements.txt
python main.py --config config.yaml
```

Find your LAN IP with `ipconfig getifaddr en0` (or `en1`).

### Pi Zero 2 W

System deps (devops handles this):
```bash
sudo apt update && sudo apt install -y \
  python3-pip mpg123 libasound2-dev bluetooth \
  pi-bluetooth bluez-alsa
```

bluez-alsa from source (Zero 2 W needs this):
```bash
git clone https://github.com/Arkq/bluez-alsa.git
cd bluez-alsa && mkdir build && cd build
cmake .. && make -j$(nproc)
sudo make install
```

App deps:
```bash
cd pi-client
cp config.example.yaml config.yaml
# set tts_server.host to your MacBook's LAN IP
pip3 install -r requirements.txt
```

Run:
```bash
# Pair phone (one-time)
./bt-bridge.sh AA:BB:CC:DD:EE:FF

# Run TTS player
python3 main.py --config config.yaml
```

### Kick Webhook Server

System deps (same as tts-server):
```bash
pip install -r requirements.txt
```

OAuth setup (first time):
1. Create app at https://kick.com/developer
2. Note `client_id` and `client_secret`
3. Get your `broadcaster_user_id` from `GET /public/v1/channels/{username}`
4. Subscribe to events:
```bash
curl -X POST https://api.kick.com/public/v1/events/subscriptions \
  -H "Authorization: Bearer $KICK_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"event_types": ["channel.followed","channel.subscription.new","channel.subscription.gifts"], "broadcaster_user_id": YOUR_ID}'
```

Run:
```bash
cd kick-webhook-server
cp config.example.yaml config.yaml
# fill in client_id, client_secret, broadcaster_user_id, oauth_token
python main.py --config config.yaml
```

Cloudflare Tunnel must point port 8081 to the MacBook for Kick to reach the webhook.

## Event Types

### Rumble (tts-server)

Enabled by default in `tts-server/config.example.yaml`:

| Event | Default | Note |
|-------|---------|------|
| `new_follower` | ✅ | |
| `new_subscriber` | ✅ | |
| `gifted_sub` | ✅ | |
| `live_on` | ✅ | |
| `live_off` | ❌ | Off by default — verbose |
| `rant` | ✅ | Superchats/rants |
| `chat_message` | ❌ | Off by default — very high volume |

### Kick (kick-webhook-server)

Enabled by default in `kick-webhook-server/config.example.yaml`:

| Event | Default | Note |
|-------|---------|------|
| `channel.followed` | ✅ | |
| `channel.subscription.new` | ✅ | |
| `channel.subscription.gifts` | ✅ | |
| `channel.subscription.renewal` | ❌ | Off by default — too noisy |
| `chat.message.sent` | ❌ | Off by default — very high volume |

## Audio Mixing

Both TTS and phone BT audio play through the same 3.5mm jack. ALSA `dmix` plugin on the Pi handles mixing automatically — no pulseaudio needed. Both streams open the hardware device independently and `dmix` interleaves them.

## Configuration

### tts-server/config.example.yaml

```yaml
rumble:
  api_url: "https://api.rumble.com/live_stream/v1.1/updates"
  api_key: "YOUR_RUMBLE_API_KEY"
  poll_interval_seconds: 30

tts:
  voice: "en-US-AriaNeural"
  rate: "+0%"
  volume: "+0%"

server:
  host: "0.0.0.0"
  port: 8080
  spool_dir: "spool"

events:
  new_follower: true
  new_subscriber: true
  gifted_sub: true
  live_on: true
  live_off: false
  chat_message: false
  rant: true
```

### pi-client/config.example.yaml

```yaml
tts_server:
  host: "192.168.1.100"   # your MacBook LAN IP
  port: 8080

player:
  poll_interval_seconds: 5
  volume: 90
```

### kick-webhook-server/config.example.yaml

```yaml
kick:
  oauth_token: "YOUR_KICK_ACCESS_TOKEN"
  client_id: "YOUR_CLIENT_ID"
  client_secret: "YOUR_CLIENT_SECRET"
  broadcaster_user_id: 123456

server:
  host: "0.0.0.0"
  port: 8081
  spool_dir: "../spool"   # shared with tts-server

tts:
  voice: "en-US-AriaNeural"
  rate: "+0%"
  volume: "+0%"

events:
  channel.followed: true
  channel.subscription.new: true
  channel.subscription.gifts: true
  channel.subscription.renewal: false
  chat.message.sent: false
```

## Auto-Deploy (GitHub Actions)

Releases are auto-deployed to the Pi via GitHub Actions. On every new GitHub Release, the workflow:
1. Checks out the tag
2. Rsyncs `kick-webhook-server/` to the Pi via SSH
3. Installs deps in the venv on the Pi
4. Restarts the `kick-webhook-server` systemd service
5. Hits `/health` to verify

See `.github/workflows/release.yml` for the workflow.

**Required GitHub Secrets** (add at https://github.com/milanbede/KITT/settings/secrets/actions):
- `PI_SSH_KEY` — private key for `milan-bede` user
- `PI_HOST` — Pi IP or domain (e.g. `192.168.7.170` or tunnel endpoint)
- `PI_USER` — `milan-bede`

## License

MIT
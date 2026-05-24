# rumble-tts-bridge

> MacBook polls Rumble API → edge-tts MP3s → Pi Zero 2 W pulls and plays → same speaker for music and TTS alerts.

## Status

🔴 Planning complete — implementation not started.

## Architecture

```
[Rumble API] ──► [MacBook: poller + edge-tts] ──► [HTTP :8080]
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

## Event Types

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

## License

MIT
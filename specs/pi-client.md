# SPEC: pi-client (rumble-tts-bridge)

🔴 Not implemented

---

## Overview

`pi-client` runs on the Pi Zero 2 W. It polls the MacBook HTTP server for new MP3 files, plays them via pygame, sends an ACK, deletes the local file, and bridges phone BT audio to the same speaker output.

---

## Requirements

### R1 — Config loading (pi-client)

**Test:** `tests/test_config.py`
1. `load_config()` returns a dict with all required keys
2. `tts_server.host` and `tts_server.port` are used to build the base URL
3. `player.volume` is an integer 0–100
4. `player.poll_interval_seconds` is an integer

**Implementation:** `config.py`

---

### R2 — TTSPlayer polling

**Test:** `tests/test_player.py`
1. `TTSPlayer(server_url, cache_dir, volume)` initializes without errors
2. `run(poll_interval)` starts the polling loop
3. `GET /` returns list of files; each `.mp3` not in `seen` is a new job
4. Known `.mp3` in `seen` is skipped
5. Non-`.mp3` files are skipped

**Implementation:** `player.py`

---

### R3 — TTSPlayer download

**Test:** `tests/test_player.py`
1. `GET /{filename}.mp3` is called for new files
2. Response body is written to `cache_dir/{filename}.mp3`
3. Download failure (404, timeout, network error) does not crash the loop
4. Partial/incomplete MP3 download is not played (wait for complete)

**Implementation:** `player.py`

---

### R4 — TTSPlayer playback

**Test:** `tests/test_player.py`
1. `pygame.mixer.init()` is called before first playback
2. `pygame.mixer.music.load()` is called with the local cached file
3. `pygame.mixer.music.play()` is called
4. `pygame.mixer.music.get_busy()` loop blocks until playback finishes
5. `pygame.mixer.music.set_volume(volume/100)` is called with correct volume
6. Playback failure does not crash the loop

**Implementation:** `player.py`

---

### R5 — TTSPlayer ACK

**Test:** `tests/test_player.py`
1. After successful playback, `POST /ack` is sent with `{"filename": "..."}`
2. ACK failure (network error) does not crash the loop
3. ACK failure does not delete the local file (leaves cleanup for next run)
4. After ACK, local file is deleted

**Implementation:** `player.py`

---

### R6 — Concurrent playback

**Test:** `tests/test_player.py`
1. When a new MP3 arrives while one is playing, the new one starts after the current one finishes (sequential, not parallel)
2. Polling continues while playback is in progress (doesn't block poll loop)

**Implementation:** `player.py` — each `_play()` runs in a background thread

---

### R7 — Main wiring

**Test:** `tests/test_main.py` (integration test)
1. `load_config()` is called with `--config` argument
2. `TTSPlayer` is initialized with `server_url`, `volume` from config
3. `player.run(poll_interval)` is the blocking loop

**Implementation:** `main.py`

---

### R8 — BT bridge script

**Test:** `tests/test_bt_bridge.sh`
Manual verification — no automated test. Devops verifies manually.

1. `bt-bridge.sh <mac>` accepts a BT MAC address
2. `bluetoothctl power on` is called
3. Device is trusted and paired via `bluetoothctl`
4. `bluezalsa-cli` or `bluealsa-aplay` is invoked in background
5. ALSA card is visible: `aplay -l` shows a `bluez_output` device
6. Phone connects via BT A2DP — audio plays through the jack
7. TTS and BT audio mix on the same output (no dropout, no blocking)

**Implementation:** `bt-bridge.sh`

---

## File Structure

```
pi-client/
├── config.example.yaml
├── requirements.txt
├── main.py         # entry point
├── config.py       # load_config()
└── player.py       # TTSPlayer
```

```
tests/
├── test_config.py
└── test_player.py
```

---

## Dependencies

```
pyyaml>=6.0
requests>=2.31.0
pygame>=2.5.0
```

No pygame.mixer fallback needed — Pi Zero 2 W can handle pygame.

---

## Config Keys (required)

```yaml
tts_server.host: str   # e.g. "192.168.1.100"
tts_server.port: int   # default: 8080

player.poll_interval_seconds: int (default: 5)
player.volume: int (default: 90)
```

---

## Acceptance Criteria

- [ ] R1: Config loads correctly on Pi Zero
- [ ] R2: Polling loop detects new MP3s and skips already-seen files
- [ ] R3: Downloads are complete before playback starts
- [ ] R4: Playback works via pygame and respects volume setting
- [ ] R5: ACK is sent and local file deleted after playback
- [ ] R6: Multiple files handled sequentially without blocking the poll loop
- [ ] R7: Main entry point wires all components
- [ ] R8: BT bridge script pairs phone and routes audio to jack output
- [ ] All tests pass: `pytest tests/ -v`
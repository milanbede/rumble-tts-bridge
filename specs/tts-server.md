# SPEC: tts-server (rumble-tts-bridge)

🔴 Not implemented

---

## Overview

`tts-server` runs on the MacBook. It polls Rumble's Live Stream API, generates MP3 TTS files on new events, and serves them over HTTP to the Pi Zero client.

---

## Requirements

### R1 — Config loading

**Test:** `tests/test_config.py`
1. `load_config()` returns a dict with all required keys
2. Missing required key raises `KeyError` with the key name
3. Config is loaded from the file path passed via `--config`

**Implementation:** `config.py`

---

### R2 — StateStore (deduplication)

**Test:** `tests/test_state.py`
1. `StateStore(path)` creates `state.json` in `path` if it doesn't exist
2. `seen(event_type, event_id)` returns `False` for a new ID
3. After `mark(event_type, event_id)`, `seen(event_type, event_id)` returns `True`
4. Different `event_type` values are independent (marking `follower/u123` doesn't mark `subscriber/u123`)
5. `seen()` on a previously marked ID returns `True` after process restart (persistence)

**Implementation:** `state.py`

---

### R3 — Rumble API poller

**Test:** `tests/test_poller.py`
1. `RumblePoller` takes `api_url`, `api_key`, `state`, `config`
2. `poll()` calls the API URL with `Authorization: Bearer <key>` header
3. Network failure returns `[]` (no exception raised)
4. `_extract_events()` from sample payload produces one `new_follower` event for `latest_follower`
5. Duplicate `latest_follower.username` is skipped (state returns `True` from `seen()`)
6. `new_subscriber` event has text `"New subscriber: {username}, {amount} dollars"`
7. `gifted_sub` event has text `"Gifted sub from {purchased_by}"`
8. `live_on` event fires when stream `is_live: true` and wasn't live before
9. `live_off` is NOT emitted (disabled in default config)
10. `rant` event has text starting with `"Rant: {username} said:"`
11. `poll()` returns empty list on malformed JSON (no exception)
12. `run(callback)` calls `callback(event)` for each new event, then sleeps `poll_interval_seconds`

**Implementation:** `poller.py`

---

### R4 — edge-tts wrapper

**Test:** `tests/test_tts.py`
1. `TTSEngine(spool_dir, voice, rate, volume)` stores all params
2. `speak(text)` returns a `Path` object ending in `.mp3`
3. The returned path is inside `spool_dir`
4. File at returned path is a valid MP3 (starts with bytes that a decoder recognizes)
5. `speak()` raises `Exception` on network failure (edge-tts unreachable)
6. `speak(text, job_id="custom")` uses `custom` as the filename stem

**Note:** `edge-tts` must be installed: `pip install edge-tts`

**Implementation:** `tts.py`

---

### R5 — HTTP server

**Test:** `tests/test_server.py`
1. `GET /{filename}.mp3` returns 200 with `Content-Type: audio/mpeg` and the file content
2. `GET /{nonexistent}.mp3` returns 404
3. `GET /` returns 200 with JSON listing files in spool dir
4. `POST /ack` with `{"filename": "x.mp3"}` deletes the file from spool and returns 200
5. `POST /ack` with nonexistent file returns 200 (idempotent delete)
6. `POST /ack` with missing `filename` key returns 400
7. Server starts on `host:port` from config
8. Multiple concurrent requests are handled correctly (no race in file serving)

**Implementation:** `server.py` using stdlib `http.server` (no Flask/FastAPI dep)

---

### R6 — Main wiring

**Test:** `tests/test_main.py` (integration test, skips network)
1. `load_config()` is called with `--config` argument
2. `StateStore` is initialized with `spool_dir` from config
3. `TTSEngine` is initialized with voice/rate/volume from config
4. `RumblePoller` is initialized with api_url/api_key/state/config
5. `make_app()` is called with host/port/spool_dir from config
6. `poller.run(on_event)` is the blocking loop

**Implementation:** `main.py`

---

## File Structure

```
tts-server/
├── config.example.yaml
├── requirements.txt
├── main.py          # entry point
├── config.py        # load_config()
├── state.py         # StateStore
├── poller.py        # RumblePoller, Event
├── tts.py           # TTSEngine
└── server.py        # make_app() HTTP server
```

```
tests/
├── test_config.py
├── test_state.py
├── test_poller.py
├── test_tts.py
├── test_server.py
└── test_main.py
```

---

## Dependencies

```
edge-tts>=6.1.0
pyyaml>=6.0
requests>=2.31.0
```

No Flask, no FastAPI — stdlib only for the HTTP server.

---

## Config Keys (required)

```yaml
rumble.api_url: str
rumble.api_key: str
rumble.poll_interval_seconds: int (default: 30)

tts.voice: str (default: "en-US-AriaNeural")
tts.rate: str (default: "+0%")
tts.volume: str (default: "+0%")

server.host: str (default: "0.0.0.0")
server.port: int (default: 8080)
server.spool_dir: str (default: "spool")

events.new_follower: bool (default: true)
events.new_subscriber: bool (default: true)
events.gifted_sub: bool (default: true)
events.live_on: bool (default: true)
events.live_off: bool (default: false)
events.chat_message: bool (default: false)
events.rant: bool (default: true)
```

---

## Acceptance Criteria

- [ ] R1: Config loading works with all keys present
- [ ] R2: StateStore persists across restarts
- [ ] R3: All 12 event extraction cases pass
- [ ] R4: TTS generates valid MP3 files
- [ ] R5: HTTP server serves and deletes files correctly
- [ ] R6: Main entry point wires all components
- [ ] All tests pass: `pytest tests/ -v`
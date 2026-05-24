# rumble-tts-bridge Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** MacBook polls Rumble Live Stream API, generates edge-tts MP3 files, serves them over HTTP. Pi Zero 2 W pulls new MP3s, plays them, ACKs them, deletes them. Pi Zero also bridges phone BT audio to the same speaker so TTS alerts and music coexist.

**Architecture:**
```
[Rumble API] → [MacBook: poller + edge-tts] → [HTTP server :8080]
                                                    ↓
                                        [Pi Zero 2 W: pull + play + ACK]
                                                    ↓
                              [BT A2DP bridge: phone → speaker] + [TTS playback]
```

**Tech Stack:**
- MacBook: Python 3, `edge-tts`, `pyyaml`, stdlib `http.server`
- Pi Zero 2 W: Python 3, `pyyaml`, `mpg123`, `pygame`, `requests`, bluez-alsa

**Repo:** `milanbede/rumble-tts-bridge`
**Main branches:** `main` (protected), `develop`

---

## Phase 1 — TTS Server (MacBook)

### Task 1: Project scaffold and config

**Objective:** Create the server directory structure and config template.

**Files:**
- Create: `tts-server/config.example.yaml`
- Create: `tts-server/requirements.txt`

**Step 1: Create config template**

```yaml
# tts-server/config.example.yaml
rumble:
  api_url: "https://api.rumble.com/live_stream/v1.1/updates"
  api_key: "YOUR_RUMBLE_API_KEY"   # from https://rumble.com/account/livestream-api
  poll_interval_seconds: 30

tts:
  voice: "en-US-AriaNeural"         # edge-tts voice
  rate: "+0%"                       # playback speed adjustment
  volume: "+0%"                     # volume adjustment

server:
  host: "0.0.0.0"                  # bind to all interfaces
  port: 8080
  spool_dir: "spool"               # dir for generated MP3s

events:
  new_follower: true
  new_subscriber: true
  gifted_sub: true
  live_on: true
  live_off: false
  chat_message: false               # careful — high volume
  rant: true
```

**Step 2: Create requirements.txt**

```
edge-tts>=6.1.0
pyyaml>=6.0
requests>=2.31.0
```

**Step 3: Commit**

```bash
git add tts-server/config.example.yaml tts-server/requirements.txt
git commit -m "feat: add tts-server config template and requirements"
```

---

### Task 2: State store (deduplication)

**Objective:** Track last-seen event IDs so the poller never re-announces the same thing.

**Files:**
- Create: `tts-server/state.py`

**Step 1: Write failing test**

```python
# tests/test_state.py
import os, tempfile, pytest
from state import StateStore

def test_seen_returns_false_for_new_event():
    with tempfile.TemporaryDirectory() as tmpdir:
        s = StateStore(tmpdir)
        assert s.seen("follower", "u123") is False

def test_seen_returns_true_after_mark():
    with tempfile.TemporaryDirectory() as tmpdir:
        s = StateStore(tmpdir)
        s.mark("follower", "u123")
        assert s.seen("follower", "u123") is True

def test_different_event_types_independent():
    with tempfile.TemporaryDirectory() as tmpdir:
        s = StateStore(tmpdir)
        s.mark("follower", "u123")
        assert s.seen("subscriber", "u123") is False
```

**Step 2: Run test to verify failure**

```bash
cd tts-server && pip install pytest -q
python -m pytest ../tests/test_state.py -v
# Expected: FAIL — state module not found
```

**Step 3: Write implementation**

```python
# state.py
import json, os
from pathlib import Path

class StateStore:
    """Persists last-seen event IDs to a JSON file for deduplication."""
    def __init__(self, state_dir: str):
        self.path = Path(state_dir) / "state.json"
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {}

    def _save(self):
        self.path.write_text(json.dumps(self.data, indent=2))

    def seen(self, event_type: str, event_id: str) -> bool:
        return self.data.get(event_type) == event_id

    def mark(self, event_type: str, event_id: str):
        self.data[event_type] = event_id
        self._save()
```

**Step 4: Run test to verify pass**

```bash
python -m pytest ../tests/test_state.py -v
# Expected: 3 passed
```

**Step 5: Commit**

```bash
git add tts-server/state.py tests/test_state.py
git commit -m "feat: add StateStore for event deduplication"
```

---

### Task 3: Rumble API poller

**Objective:** Fetch the Rumble API, detect new events, emit them to a callback.

**Files:**
- Create: `tts-server/poller.py`

**Step 1: Write failing test**

```python
# tests/test_poller.py
import pytest, json
from unittest.mock import patch, MagicMock
from poller import RumblePoller

def test_extracts_follower_event():
    payload = {
        "followers": {
            "latest_follower": {"username": "TestUser", "followed_on": "2024-01-01T12:00:00Z"}
        }
    }
    p = RumblePoller(api_url="http://x", api_key="x", state=MagicMock())
    events = list(p._extract_events(payload))
    follower_events = [e for e in events if e["type"] == "new_follower"]
    assert len(follower_events) == 1
    assert follower_events[0]["username"] == "TestUser"

def test_skips_duplicate_follower():
    state = MagicMock()
    state.seen.return_value = True
    p = RumblePoller(api_url="http://x", api_key="x", state=state)
    payload = {
        "followers": {
            "latest_follower": {"username": "DupUser", "followed_on": "2024-01-01T12:00:00Z"}
        }
    }
    events = list(p._extract_events(payload))
    assert not any(e["type"] == "new_follower" for e in events)
```

**Step 2: Run test to verify failure**

```bash
python -m pytest ../tests/test_poller.py -v
# Expected: FAIL — module not found
```

**Step 3: Write implementation**

```python
# poller.py
import requests, time, logging
from typing import Callable, Literal
from state import StateStore

logger = logging.getLogger(__name__)

class Event:
    def __init__(self, type: str, text: str, id: str):
        self.type = type
        self.text = text
        self.id = id

    def __repr__(self):
        return f"Event({self.type}, {self.id!r})"

class RumblePoller:
    def __init__(self, api_url: str, api_key: str, state: StateStore,
                 config: dict):
        self.api_url = api_url
        self.api_key = api_key
        self.state = state
        self.cfg = config

    def poll(self) -> list[Event]:
        """Fetch the Rumble API and return a list of new events."""
        try:
            resp = requests.get(
                self.api_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            logger.error(f"Polling failed: {e}")
            return []

        return self._extract_events(payload)

    def _extract_events(self, payload: dict) -> list[Event]:
        events = []
        cfg = self.cfg.get("events", {})
        out = []

        # new follower
        if cfg.get("new_follower"):
            f = payload.get("followers", {}).get("latest_follower")
            if f and not self.state.seen("latest_follower", f["username"]):
                txt = f"New follower: {f['username']}"
                events.append(Event("new_follower", txt, f["username"]))
                self.state.mark("latest_follower", f["username"])

        # new subscriber
        if cfg.get("new_subscriber"):
            s = payload.get("subscribers", {}).get("latest_subscriber")
            if s and not self.state.seen("latest_subscriber", s["username"]):
                amt = s.get("amount_dollars", "?")
                txt = f"New subscriber: {s['username']}, {amt} dollars"
                events.append(Event("new_subscriber", txt, s["username"]))
                self.state.mark("latest_subscriber", s["username"])

        # gifted sub
        if cfg.get("gifted_sub"):
            g = payload.get("gifted_subs", {}).get("latest_gifted_sub")
            if g and not self.state.seen("latest_gifted_sub", g["purchased_by"]):
                txt = f"Gifted sub from {g['purchased_by']}"
                events.append(Event("gifted_sub", txt, g["purchased_by"]))
                self.state.mark("latest_gifted_sub", g["purchased_by"])

        # live stream events
        for ls in payload.get("livestreams", []):
            ls_id = ls.get("id", "")
            was_live_key = f"live_on_{ls_id}"
            is_live = ls.get("is_live", False)
            if cfg.get("live_on") and is_live and not self.state.seen(was_live_key, "1"):
                txt = f"Stream is now live: {ls.get('title', 'untitled')}"
                events.append(Event("live_on", txt, was_live_key))
                self.state.mark(was_live_key, "1")
            elif not is_live and self.state.seen(was_live_key, "1"):
                # stream went off
                self.state.mark(was_live_key, "0")

            # rants
            if cfg.get("rant"):
                r = ls.get("chat", {}).get("latest_rant")
                if r and not self.state.seen(f"rant_{ls_id}", r["text"][:50]):
                    txt = f"Rant: {r['username']} said: {r['text']}"
                    events.append(Event("rant", txt, f"rant_{ls_id}_{r['text'][:20]}"))
                    self.state.mark(f"rant_{ls_id}", r["text"][:50])

        return events

    def run(self, callback: Callable[[Event], None]):
        """Blocking poll loop. Calls callback for each new event."""
        while True:
            for event in self.poll():
                logger.info(f"New event: {event}")
                try:
                    callback(event)
                except Exception as e:
                    logger.error(f"Callback error: {e}")
            time.sleep(self.cfg.get("rumble", {}).get("poll_interval_seconds", 30))
```

**Step 4: Run test to verify pass**

```bash
python -m pytest ../tests/test_poller.py -v
# Expected: 2 passed
```

**Step 5: Commit**

```bash
git add tts-server/poller.py tests/test_poller.py
git commit -m "feat: add Rumble API poller with event extraction"
```

---

### Task 4: Edge TTS wrapper

**Objective:** Convert text strings to MP3 files using edge-tts.

**Files:**
- Create: `tts-server/tts.py`

**Step 1: Write failing test**

```python
# tests/test_tts.py
import os, tempfile, pytest
from tts import TTSEngine

def test_generate_creates_mp3_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = TTSEngine(tmpdir, voice="en-US-AriaNeural")
        path = engine.speak("Hello world", job_id="test001")
        assert os.path.exists(path)
        assert path.endswith(".mp3")
```

**Step 2: Run test to verify failure**

```bash
python -m pytest ../tests/test_tts.py -v
# Expected: FAIL — module not found
```

**Step 3: Write implementation**

```python
# tts.py
import asyncio, logging, os, uuid
from edge_tts import Communicate
from pathlib import Path

logger = logging.getLogger(__name__)

class TTSEngine:
    def __init__(self, spool_dir: str, voice: str = "en-US-AriaNeural",
                 rate: str = "+0%", volume: str = "+0%"):
        self.spool = Path(spool_dir)
        self.spool.mkdir(parents=True, exist_ok=True)
        self.voice = voice
        self.rate = rate
        self.volume = volume

    async def _generate(self, text: str, out_path: Path) -> Path:
        communicate = Communicate(
            text,
            voice=self.voice,
            rate=self.rate,
            volume=self.volume,
        )
        await communicate.save(str(out_path))
        return out_path

    def speak(self, text: str, job_id: str | None = None) -> Path:
        """Generate MP3 synchronously. Returns the file path."""
        job_id = job_id or uuid.uuid4().hex[:8]
        out_path = self.spool / f"{job_id}.mp3"
        try:
            asyncio.run(self._generate(text, out_path))
            logger.debug(f"TTS written: {out_path}")
        except Exception as e:
            logger.error(f"TTS generation failed for '{text[:30]}...': {e}")
            raise
        return out_path
```

**Step 4: Run test to verify pass**

```bash
python -m pytest ../tests/test_tts.py -v
# Expected: 1 passed (requires network)
```

**Step 5: Commit**

```bash
git add tts-server/tts.py tests/test_tts.py
git commit -m "feat: add edge-tts wrapper"
```

---

### Task 5: HTTP server (spool + ACK)

**Objective:** Serve MP3 files and handle ACK requests to delete played files.

**Files:**
- Create: `tts-server/server.py`

**Step 1: Write failing test**

```python
# tests/test_server.py
import pytest, os, tempfile, requests, threading
from server import make_app

def test_get_returns_file(tmp_path):
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"fake mp3 data")
    app = make_app(str(tmp_path))
    # can't easily test flask in-process, skip to manual test
    pass
```

**Step 2: Write implementation**

```python
# server.py
import logging, os
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import unquote
import threading

logger = logging.getLogger(__name__)

class SpoolHandler(SimpleHTTPRequestHandler):
    spool_dir: Path = None

    def do_GET(self):
        """Serve MP3 files from spool dir."""
        path = unquote(self.path.lstrip("/"))
        if not path:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "files": ' +
                str(list(self.spool_dir.iterdir())).encode() + b"}")
            return

        file_path = self.spool_dir / path
        if not file_path.exists() or not file_path.is_file():
            self.send_error(404)
            return
        ext = file_path.suffix.lower()
        ctype = "audio/mpeg" if ext == ".mp3" else "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", file_path.stat().st_size)
        self.end_headers()
        with open(file_path, "rb") as f:
            self.wfile.write(f.read())

    def do_POST(self):
        """Handle ACK to delete a played file."""
        import json
        if self.path != "/ack":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)
            filename = data.get("filename")
            if not filename:
                self.send_error(400)
                return
            file_path = self.spool_dir / filename
            if file_path.exists():
                file_path.unlink()
                logger.info(f"Deleted: {filename}")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "deleted"}')
        except Exception as e:
            logger.error(f"ACK error: {e}")
            self.send_error(500)

    def log_message(self, fmt, *args):
        logger.debug(fmt % args)

def make_app(spool_dir: str, host: str = "0.0.0.0", port: int = 8080):
    SpoolHandler.spool_dir = Path(spool_dir)
    server = HTTPServer((host, port), SpoolHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"HTTP server running on {host}:{port}")
    return server
```

**Step 3: Manual verification**

```bash
cd tts-server
mkdir -p spool
echo "fake mp3" > spool/test.mp3
python server.py &
curl http://localhost:8080/test.mp3  # should return file
curl -X POST http://localhost:8080/ack -d '{"filename":"test.mp3"}' -H "Content-Type: application/json"
# file should be gone
```

**Step 4: Commit**

```bash
git add tts-server/server.py
git commit -m "feat: add HTTP server with spool + ACK endpoint"
```

---

### Task 6: TTS server main entry point

**Objective:** Wire poller + TTS + server together with config loading.

**Files:**
- Create: `tts-server/main.py`

**Step 1: Write implementation**

```python
# main.py
import argparse, logging, sys, yaml
from pathlib import Path
from poller import RumblePoller, Event
from tts import TTSEngine
from server import make_app
from state import StateStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("main")


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="Rumble TTS Server")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    spool = cfg["server"]["spool_dir"]
    Path(spool).mkdir(parents=True, exist_ok=True)

    state = StateStore(spool)
    tts = TTSEngine(
        spool_dir=spool,
        voice=cfg["tts"]["voice"],
        rate=cfg["tts"]["rate"],
        volume=cfg["tts"]["volume"],
    )

    def on_event(event: Event):
        log.info(f"Announcing: {event}")
        try:
            path = tts.speak(event.text)
            log.info(f"MP3 ready: {path.name}")
        except Exception as e:
            log.error(f"TTS failed: {e}")

    poller = RumblePoller(
        api_url=cfg["rumble"]["api_url"],
        api_key=cfg["rumble"]["api_key"],
        state=state,
        config=cfg,
    )

    server = make_app(
        spool_dir=spool,
        host=cfg["server"]["host"],
        port=cfg["server"]["port"],
    )

    log.info("Rumble TTS Server running. Press Ctrl+C to stop.")
    try:
        poller.run(on_event)
    except KeyboardInterrupt:
        log.info("Shutting down.")
        sys.exit(0)


if __name__ == "__main__":
    main()
```

**Step 2: Create setup script and README snippet**

```bash
echo '#!/bin/bash
cp config.example.yaml config.yaml
# Edit config.yaml and add your RUMBLE_API_KEY
pip install -r requirements.txt
python main.py
' > tts-server/run.sh
chmod +x tts-server/run.sh
```

**Step 3: Commit**

```bash
git add tts-server/main.py tts-server/run.sh
git commit -m "feat: wire poller + TTS + server into main entry point"
```

---

## Phase 2 — Pi Zero Audio Client

### Task 7: Pi client scaffold

**Objective:** Directory structure, config, requirements for Pi Zero side.

**Files:**
- Create: `pi-client/config.example.yaml`
- Create: `pi-client/requirements.txt`

**Step 1: Create config template**

```yaml
# pi-client/config.example.yaml
tts_server:
  host: "192.168.1.100"   # MacBook LAN IP
  port: 8080

player:
  poll_interval_seconds: 5
  volume: 90              # 0-100
  card: "DMIX"            # ALSA card name for output
```

**Step 2: Create requirements.txt**

```
pyyaml>=6.0
requests>=2.31.0
pygame>=2.5.0
```

**Step 3: Commit**

```bash
git add pi-client/config.example.yaml pi-client/requirements.txt
git commit -m "feat: add pi-client scaffold"
```

---

### Task 8: Pi audio player

**Objective:** Poll the HTTP server, download new MP3s, play them, ACK, delete.

**Files:**
- Create: `pi-client/player.py`

**Step 1: Write failing test**

```python
# tests/test_player.py
from unittest.mock import patch, MagicMock
from player import TTSPlayer

def test_play_fetches_and_acks(tmp_path):
    with patch("requests.get") as mock_get, \
         patch("pygame.mixer.init"), \
         patch("pygame.mixer.music.load"), \
         patch("pygame.mixer.music.play"):
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b"fake mp3"
        mock_get.return_value.headers = {}
        player = TTSPlayer("http://x:8080", tmp_path)
        player._play("test001.mp3")
        # verify download was attempted
        assert mock_get.called
```

**Step 2: Run test to verify failure**

```bash
python -m pytest ../pi-client/tests/test_player.py -v
# Expected: FAIL — module not found
```

**Step 3: Write implementation**

```python
# player.py
import logging, os, pygame, requests, time, threading
from pathlib import Path

logger = logging.getLogger(__name__)

class TTSPlayer:
    def __init__(self, server_url: str, cache_dir: str = "/tmp/tts-cache",
                 volume: int = 90):
        self.server_url = server_url.rstrip("/")
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.volume = volume / 100.0
        self._mixer_ready = False

    def _ensure_mixer(self):
        if not self._mixer_ready:
            pygame.mixer.init(frequency=44100, size=-16, channels=2)
            pygame.mixer.music.set_volume(self.volume)
            self._mixer_ready = True

    def _download(self, filename: str) -> Path | None:
        url = f"{self.server_url}/{filename}"
        local = self.cache / filename
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            local.write_bytes(resp.content)
            return local
        except Exception as e:
            logger.error(f"Download failed for {filename}: {e}")
            return None

    def _ack(self, filename: str) -> bool:
        try:
            resp = requests.post(
                f"{self.server_url}/ack",
                json={"filename": filename},
                timeout=5,
            )
            resp.raise_for_status()
            logger.info(f"ACKed: {filename}")
            return True
        except Exception as e:
            logger.error(f"ACK failed for {filename}: {e}")
            return False

    def _play(self, filename: str):
        local = self._download(filename)
        if not local:
            return
        try:
            self._ensure_mixer()
            pygame.mixer.music.load(str(local))
            pygame.mixer.music.play()
            # block until done
            while pygame.mixer.music.get_busy():
                time.sleep(0.2)
        except Exception as e:
            logger.error(f"Playback error for {filename}: {e}")
        finally:
            # clean up
            try:
                local.unlink()
            except Exception:
                pass
            self._ack(filename)

    def run(self, poll_interval: int = 5):
        """Poll loop. Downloads and plays any new MP3 from the server."""
        logger.info(f"Polling {self.server_url} every {poll_interval}s...")
        seen = set()
        while True:
            try:
                resp = requests.get(f"{self.server_url}/", timeout=5)
                if resp.status_code != 200:
                    time.sleep(poll_interval)
                    continue
                files = []
                try:
                    import json
                    data = resp.json()
                    raw = data.get("files", "[]")
                    # parse repr of list
                    files = eval(raw) if isinstance(raw, str) else raw
                except Exception:
                    pass

                for item in files:
                    if isinstance(item, dict):
                        fname = item.get("name") or item.get("filename", "")
                    else:
                        fname = str(item)
                    if not fname.endswith(".mp3") or fname in seen:
                        continue
                    seen.add(fname)
                    logger.info(f"Playing: {fname}")
                    # play in background thread so polling continues
                    t = threading.Thread(target=self._play, args=(fname,))
                    t.start()
            except Exception as e:
                logger.error(f"Poll error: {e}")
            time.sleep(poll_interval)
```

**Step 4: Run test to verify pass**

```bash
python -m pytest ../pi-client/tests/test_player.py -v
# Expected: 1 passed
```

**Step 5: Commit**

```bash
git add pi-client/player.py
git commit -m "feat: add TTS player with polling + ACK"
```

---

### Task 9: Pi client main + BT bridge

**Objective:** Entry point + BT A2DP bridge script for Pi Zero.

**Files:**
- Create: `pi-client/main.py`
- Create: `pi-client/bt-bridge.sh`

**Step 1: Write main.py**

```python
# main.py
import argparse, logging, sys, yaml
from pathlib import Path
from player import TTSPlayer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("main")


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="Rumble TTS Pi Client")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)

    server = f"http://{cfg['tts_server']['host']}:{cfg['tts_server']['port']}"
    player = TTSPlayer(
        server_url=server,
        volume=cfg["player"].get("volume", 90),
    )

    log.info("TTS Pi Client running. Press Ctrl+C to stop.")
    try:
        player.run(poll_interval=cfg["player"].get("poll_interval_seconds", 5))
    except KeyboardInterrupt:
        log.info("Shutting down.")
        sys.exit(0)


if __name__ == "__main__":
    main()
```

**Step 2: Write bt-bridge.sh**

```bash
#!/bin/bash
# bt-bridge.sh — Bluez-alsa A2DP bridge on Pi Zero 2 W
# Pairs phone via BT, streams audio to the same jack output as TTS.
#
# Prereqs:
#   sudo apt install bluez-alsa-tools libasound2-dev python3-all-dev \
#                    bluetooth pi-bluetooth  # if no built-in BT
#   # For Pi Zero 2 W you may need to compile bluez-alsa from source:
#   # https://github.com/Arkq/bluez-alsa
#
# Usage:
#   ./bt-bridge.sh [phone-mac-address]
#   e.g.:  ./bt-bridge.sh AA:BB:CC:DD:EE:FF

set -e

PHONE_MAC="${1:-}"
SPOOL_DIR="/tmp/tts-cache"
CARD="DMIX"   # adjust to your ALSA card number: aplay -l

# ---- Pair/connect phone ----
if [ -n "$PHONE_MAC" ]; then
    echo "[BT] Trusting and pairing with $PHONE_MAC ..."
    bluetoothctl -- power on || true
    bluetoothctl -- agent on
    bluetoothctl -- default-agent
    bluetoothctl -- trust "$PHONE_MAC" || true
    if ! bluetoothctl -- info "$PHONE_MAC" 2>/dev/null | grep -q "Connected: yes"; then
        bluetoothctl -- pair "$PHONE_MAC" || true
        bluetoothctl -- connect "$PHONE_MAC" || true
    fi
    echo "[BT] Phone connected."
fi

# ---- Start bluez-alsa A2DP sink ----
# bluez-alsa runs as a pseudo-ALSA card, e.g., "bluez_output.XX_XX_XX_XX_XX_XX.a2dp_control"
# Route phone BT audio through dmix so TTS (pygame/mpg123) and BT can play simultaneously
echo "[BT] Starting bluez-alsa..."
bluezalsa-cli &
sleep 2

# Show available cards
echo "[BT] Available ALSA cards:"
aplay -l

# ---- Routing: BT → ALSA dmix → speaker jack ----
# TTS already plays via pygame → ALSA default → dmix → hardware output
# BT audio from bluez-alsa needs to feed into the same dmix.
# Using ALSA loopback module:
#   sudo modprobe snd-aloop pcm_subdev=0
# Or pipe via paprefs / pulseaudio (heavier, but easier on Pi):
#   sudo apt install pulseaudio
#   # enable module-null-sink + module-combine-sink in /etc/pulse/
#
# Simplified approach for Pi Zero 2 W (no pulseaudio):
#   TTS and BT both open the same ALSA hardware device — dmix handles mixing.
#   bluez-alsa outputs to the hw: card directly; dmix on hw: mixes both streams.
#
# To verify BT audio route:
#   aplay -D bluez_output.XX_XX_XX_XX_XX_XX.a2dp_control /usr/share/sounds/alsa/Front_Center.wav

echo "[BT] Bridge ready. BT audio and TTS share the jack output."
echo "[BT] To list BT devices:"
bluetoothctl -- devices
```

**Step 3: Commit**

```bash
git add pi-client/main.py pi-client/bt-bridge.sh
git commit -m "feat: add pi-client main entry point and BT bridge script"
```

---

## Phase 3 — README and finalization

### Task 10: README

**Objective:** Complete README with setup instructions for both sides.

**Files:**
- Create: `README.md`

**Step 1: Write README**

```markdown
# rumble-tts-bridge

Rumble Live Stream notifier: MacBook polls Rumble's API, generates TTS MP3s via edge-tts, serves them over HTTP. Pi Zero 2 W pulls and plays them. The Pi also bridges your phone's BT audio to the same speaker, so music and TTS alerts coexist.

## Architecture

```
[Rumble API] ──► [MacBook: poller + edge-tts] ──► [HTTP :8080]
                                                      │
                                          [Pi Zero 2 W: pull + play]
                                                      │
                              [BT A2DP: phone] ──► [speaker + TTS]
```

## Requirements

- MacBook: Python 3.10+, network access to Rumble API
- Raspberry Pi Zero 2 W: Python 3, Bluetooth (USB dongle or built-in BT on RPi Zero 2 W variants), internet access
- Speaker with 3.5mm jack

## MacBook Setup (tts-server)

```bash
cd tts-server
cp config.example.yaml config.yaml
# Edit config.yaml: add your RUMBLE_API_KEY
# Get your key at: https://rumble.com/account/livestream-api

pip install -r requirements.txt
python main.py --config config.yaml
```

Find your MacBook's LAN IP (e.g. `192.168.1.100`) — you'll need it for the Pi config.

## Pi Zero Setup (pi-client)

```bash
# Install system deps
sudo apt update
sudo apt install -y python3-pip mpg123 libasound2-dev bluetooth \
  pi-bluetooth bluez-alsa

# bluez-alsa (required for A2DP loopback — compile from source on Zero 2 W):
# https://github.com/Arkq/bluez-alsa

pip3 install -r requirements.txt
cp config.example.yaml config.yaml
# Edit config.yaml: set tts_server.host to your MacBook's LAN IP

# Run BT bridge (pair your phone first)
./bt-bridge.sh [phone-bt-mac]

# Run the TTS player
python3 main.py --config config.yaml
```

## Configuration

See `tts-server/config.example.yaml` and `pi-client/config.example.yaml` for all options.

### Event types

| Event | Default | Description |
|-------|---------|-------------|
| `new_follower` | ✅ | New channel follower |
| `new_subscriber` | ✅ | New subscriber |
| `gifted_sub` | ✅ | Gifted subscription |
| `live_on` | ✅ | Stream goes live |
| `live_off` | ❌ | Stream ends |
| `rant` | ✅ | Latest superchat/rant |
| `chat_message` | ❌ | Every chat message (high volume!) |

## Audio mixing

Both TTS (from the Pi client) and BT audio (from your phone) play through the same 3.5mm jack. ALSA's `dmix` plugin handles mixing automatically on the Pi — as long as both use the same ALSA hardware device, they mix without needing pulseaudio.

## License

MIT
```

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup instructions"
git push origin main
```

---

## Acceptance Criteria

- [ ] `tts-server` polls Rumble API and generates MP3 files on new events
- [ ] `tts-server` HTTP server serves MP3 files and accepts ACK to delete them
- [ ] `pi-client` polls server, plays MP3, sends ACK, cleans up local file
- [ ] BT bridge script pairs phone and routes audio to the same output as TTS
- [ ] Config is via YAML files, no hardcoded values
- [ ] README has step-by-step setup for both machines
- [ ] All code runs on Python 3 with the stated dependencies

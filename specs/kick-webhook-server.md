# SPEC: kick-webhook-server (rumble-tts-bridge)

✅ Implementation in progress — see kanban board `rumble-tts`

---

## Overview

`kick-webhook-server` runs on the MacBook alongside `tts-server`. It receives inbound webhook events from Kick (vs Rumble's outbound polling), maps them to TTS text, generates MP3 files, and serves them over HTTP to the Pi Zero client — the same downstream path as Rumble.

**Key differences from Rumble:**
- Kick pushes (webhooks); Rumble pulls (polling)
- OAuth2 user tokens; no API key
- ECDSA secp256k1 webhook signature verification
- Inbound HTTP server; no polling loop

---

## Architecture

```
[Kick Platform] ──► [MacBook: kick-webhook-server :8081]
                        │
                        │ (generates MP3 via edge-tts)
                        ▼
                    [HTTP :8080 spool dir]
                                  │
                                          [Pi Zero 2 W: pull + play]
```

Both `tts-server` (Rumble) and `kick-webhook-server` write to the same `spool_dir`. The Pi Zero client polls `GET /` and doesn't care which platform generated the MP3.

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
4. Different `event_type` values are independent (marking `followed/u123` doesn't mark `subscription_new/u123`)
5. `seen()` on a previously marked ID returns `True` after process restart (persistence)

**Note:** Copy `state.py` from `tts-server/` — identical implementation.

**Implementation:** `state.py`

---

### R3 — Webhook signature verification

**Test:** `tests/test_signature.py`
1. `verify_signature(payload_bytes, signature_header, public_key_pem)` returns `True` for a valid ECDSA secp256k1 signature
2. `verify_signature()` returns `False` for tampered payload
3. `verify_signature()` returns `False` for missing/malformed signature header
4. `verify_signature()` raises `ValueError` if public key is invalid

**Kick uses ECDSA secp256k1** — NOT HMAC. Kick's public key is fetched from `https://api.kick.com/public/v1/public-key`.

**Note:** Kick signs the raw request body bytes, not a JSON string. Use `request.get_data()` in Flask, not `request.get_json()`.

**Implementation:** `signature.py`

---

### R4 — Event mapping (Kick event → TTS text)

**Test:** `tests/test_events.py`
1. `_map_kick_event(event_dict)` returns `None` for unknown event types
2. `channel.followed` → `"New follower: {user['username']}"`
3. `channel.subscription.new` → `"New subscriber: {user['username']}, {amount} dollars"` (amount from `subscription['amount']`)
4. `channel.subscription.gifts` → `"Gifted sub from {gifter['username']}"`
5. `channel.subscription.renewal` → `None` (disabled — too noisy)
6. `chat.message.sent` → `None` (disabled by default; high volume)
7. Disabled event types return `None` even if mapping exists
8. Missing fields in event dict don't crash — return `None` or sensible default

**Payload structure reference** (from Kick docs):
```json
{
  "event": "channel.followed",
  "version": 1,
  "timestamp": "2024-01-01T00:00:00Z",
  "data": {
    "user": { "id": 123, "username": "someuser" },
    "followed_at": "2024-01-01T00:00:00Z"
  }
}
```

**Implementation:** `events.py`

---

### R5 — Flask webhook server

**Test:** `tests/test_webhook.py`
1. `POST /webhook` with valid signature + valid event returns 200
2. `POST /webhook` with invalid/missing signature returns 401
3. `POST /webhook` with duplicate event_id returns 200 but generates no TTS (deduped)
4. Valid non-duplicate event triggers TTS generation
5. `GET /health` returns 200 `{"status": "ok"}` (no auth required)
6. TTS file written to `spool_dir/` with format `{event_type}_{event_id}.mp3`
7. Server starts on `host:port` from config

**Note:** Use Flask (not FastAPI). Kick's webhook library reference examples use Flask.

**Flask route:**
```python
@app.route('/webhook', methods=['POST'])
def webhook():
    payload = request.get_data()  # raw bytes, NOT json
    sig = request.headers.get('X-Kick-Signature', '')
    if not verify_signature(payload, sig, public_key_pem):
        return 'Unauthorized', 401
    event = json.loads(payload)
    ...
```

**Kick signature header format:** `t={timestamp},v1={signature}`. Verify `t` matches current time ±5 min (replay protection).

**Implementation:** `webhook.py`

---

### R6 — OAuth2 token management

**Test:** `tests/test_oauth.py`
1. `refresh_oauth_token()` POSTs to `https://id.kick.com/oauth/token` with `client_credentials` grant
2. Token is cached in `state.json` with expiry timestamp
3. `get_valid_token()` returns cached token if not expired (with 60s buffer)
4. `get_valid_token()` triggers refresh if token missing or expired
5. Token refresh failure raises `RuntimeError`

**Note:** Kick uses `client_credentials` flow for webhook event subscriptions (not authorization code).

**Scope needed:** `application:events`

**Implementation:** `oauth.py`

---

### R7 — Main wiring

**Test:** `tests/test_main.py` (integration test)
1. `load_config()` is called with `--config` argument
2. `StateStore` is initialized with `spool_dir` from config
3. `TTSEngine` is initialized with voice/rate/volume from config
4. `refresh_oauth_token()` is called at startup
5. `app.run()` is called with `host:port` from config
6. OAuth token is refreshed automatically on 401 from Kick API

**Implementation:** `main.py`

---

## File Structure

```
kick-webhook-server/
├── config.example.yaml
├── requirements.txt
├── main.py          # entry point
├── config.py        # load_config()
├── state.py         # StateStore (copied from tts-server/)
├── signature.py    # verify_signature()
├── events.py        # _map_kick_event()
├── webhook.py       # Flask app, POST /webhook, GET /health
├── oauth.py         # OAuth2 token management
└── tests/
    ├── test_config.py
    ├── test_state.py
    ├── test_signature.py
    ├── test_events.py
    ├── test_webhook.py
    ├── test_oauth.py
    └── test_main.py
```

---

## Dependencies

```
flask>=3.0.0
edge-tts>=6.1.0
pyyaml>=6.0
requests>=2.31.0
cryptography>=41.0  # for ECDSA signature verification
```

---

## Config Keys (required)

```yaml
kick:
  oauth_token: str           # initial token (refreshed automatically)
  client_id: str
  client_secret: str
  broadcaster_user_id: int
  public_key_pem: str        # Kick's EC public key (fetched from api.kick.com/public/v1/public-key)

server:
  host: str (default: "0.0.0.0")
  port: int (default: 8081)
  spool_dir: str (default: "../spool")   # shared with tts-server

tts:
  voice: str (default: "en-US-AriaNeural")
  rate: str (default: "+0%")
  volume: str (default: "+0%")

events:
  channel.followed: bool (default: true)
  channel.subscription.new: bool (default: true)
  channel.subscription.gifts: bool (default: true)
  channel.subscription.renewal: bool (default: false)
  chat.message.sent: bool (default: false)
```

---

## Kick Setup Steps

1. Create OAuth app at https://kick.com/developer
2. Note `client_id` and `client_secret`
3. Get your `broadcaster_user_id` from the Channels API
4. Enable webhooks in Account Settings → Developer tab
5. Set webhook URL: `https://your-tunnel-host.kick-tunnel.dev/webhook`
6. Subscribe to events via `POST /public/v1/events/subscriptions` with `application:events` scope

**For local dev:** Cloudflare Tunnel points public URL → MacBook :8081

---

## Event Types

Enabled by default in `config.example.yaml`:

| Event | Default | TTS text |
|-------|---------|----------|
| `channel.followed` | ✅ | "New follower: {username}" |
| `channel.subscription.new` | ✅ | "New subscriber: {username}, {amount} dollars" |
| `channel.subscription.gifts` | ✅ | "Gifted sub from {gifter}" |
| `channel.subscription.renewal` | ❌ | (disabled — too noisy) |
| `chat.message.sent` | ❌ | (disabled — very high volume) |

---

## Acceptance Criteria

- [ ] R1: Config loading works with all keys present
- [ ] R2: StateStore persists across restarts
- [ ] R3: Valid ECDSA signatures pass; tampered payloads rejected
- [ ] R4: All event types map to correct TTS text; disabled events return None
- [ ] R5: Flask server receives webhooks, verifies signatures, generates TTS MP3s
- [ ] R6: OAuth tokens refresh automatically before expiry
- [ ] R7: Main entry point wires all components
- [ ] All tests pass: `pytest tests/ -v`
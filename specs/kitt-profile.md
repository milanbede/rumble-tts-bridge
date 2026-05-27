# SPEC: KITT Profile

🟡 Planning — see kanban board `rumble-tts`

---

## Overview

`kitt` is a Hermes profile that acts as a personal streaming DJ — like KITT from Knight Rider. It connects to Telegram, receives text commands, controls music on the Pi, and announces Kick stream events via TTS.

**Core jobs:**
1. **Music control** — respond to text commands via Telegram, control Pi music player via SSH + `mpc`
2. **TTS replies** — generate TTS audio for Telegram responses + write to spool for Pi simultaneous playback
3. **Kick announcements** — `kick-webhook-server` writes TTS to spool (existing path); Pi plays them; profile does NOT need to be in the event path

**What KITT is NOT:** a voice assistant. Text only via Telegram. No STT, no mic input.

---

## Architecture

```
[Telegram DM] ──► [kitt profile] ──► [LLM reasoning]
                                    │
                        ┌───────────┴───────────┐
                        │                       │
                   [TTS reply]            [music control]
                        │                       │
                ┌───────�───────┐         [SSH to Pi]
                ▼               ▼         [mpc commands]
         [send_message]    [spool/]         [music-server.py]
         [Telegram audio]  [Pi plays]      [mpd]
```

**Audio paths (separate):**
- `spool/` — TTS only: agent Telegram replies + Kick webhook announcements
- `music/` — separate: controlled via `mpc` on Pi, no spool involvement

---

## Profile: `kitt`

### Identity
- **Profile name:** `kitt`
- **Platform:** Hermes (Telegram DM)
- **Always-on:** runs 24/7 as a daemon

### Config location
- `~/.hermes/profiles/kitt/config.yaml`

### SSH access (for music)
- Host: Pi Zero 2 W (`beloved-speaker`, 192.168.7.170)
- User: `milan-bede`
- Key: `~/.hermes/profiles/admin/home/.ssh/hermes_macbook`
- Used for: `mpc` commands, playlist discovery

---

## Music Stack

### Pi side (unchanged)
- `music-server.py` — HTTP file server on port 8082 (or current port)
- `mpd` / `mpc` — music daemon + CLI
- Music library: `/home/milan-bede/music/`
- Playlists: `/home/milan-bede/music/playlists/{name}.m3u`

### KITT controls (via SSH + mpc)
| Command | mpc command | Description |
|---------|-------------|-------------|
| Play | `mpc play` | Start playback |
| Pause | `mpc pause` | Pause playback |
| Stop | `mpc stop` | Stop playback |
| Next | `mpc next` | Skip to next track |
| Prev | `mpc prev` | Go to previous track |
| Volume | `mpc volume <0-100>` | Set volume |
| Current track | `mpc current` | Show what's playing |
| Queue | `mpc playlist` | Show queue |
| Load playlist | `mpc load {name}` | Load .m3u by name |
| Add to queue | `mpc add {path}` | Add track to queue |

### Playlist discovery
- Agent SSHs to Pi: `ssh milan-bede@192.168.7.170 "ls /home/milan-bede/music/playlists/"`
- User says "play some rock" → agent picks from available `.m3u` files
- Available playlists shown on request ("what playlists do I have?")

---

## TTS Workflow (kitt replies to Telegram)

### Dual-path TTS
When KITT generates a text response for Telegram:

1. **Generate MP3** via edge-tts (same `tts.py` as tts-server)
   - Output: `/tmp/kitt_tts/{uuid}.mp3`
2. **Send to Telegram** via `send_message` (MEDIA: path)
   - User hears audio in Telegram
3. **Write to spool** at `spool/kitt_{uuid}.mp3`
   - `pi-client` picks it up and plays on Pi speaker
   - User gets audio in both places simultaneously

### Kick event announcements
- `kick-webhook-server` writes TTS to `spool/` (existing behavior)
- Pi `pi-client` plays it (existing behavior)
- KITT profile is NOT in this path — no LLM involvement needed

---

## Spool vs Music (clarification)

| Path | Contents | Player |
|------|----------|--------|
| `spool/` | TTS MP3s (agent replies + Kick announcements) | `pi-client` (HTTP poll) |
| `/home/milan-bede/music/` | Music files | `mpd` / `mpc` |

**Completely separate.** Spool has no music, music dir has no TTS.

---

## Skills

### `kitt-music-control`
- SSH to Pi
- Discover playlists via `ls /home/milan-bede/music/playlists/`
- Execute `mpc` commands
- Parse `mpc current` and `mpc playlist` output

### `kitt-tts-workflow`
- Generate TTS MP3 via edge-tts
- Dual-path deliver: Telegram `send_message` MEDIA: + spool write
- Use existing `tts.py` from `tts-server/`

---

## Dependencies

**On MacBook (kitt profile):**
- edge-tts (Python package)
- SSH client (system)
- Hermes `send_message` tool

**On Pi (unchanged):**
- `mpd` + `mpc`
- `music-server.py` (already exists)
- `/home/milan-bede/music/playlists/*.m3u`

---

## File Structure

```
KITT/                                  # repo root (renamed from rumble-tts-bridge)
├── specs/
│   ├── kick-webhook-server.md         # existing
│   └── kitt-profile.md                # NEW
├── tts-server/                        # existing
├── kick-webhook-server/               # existing
├── spool/                             # existing, TTS only
├── pi-client/                          # existing (on Pi)
│   └── music/                         # existing music library on Pi
│       └── playlists/                # *.m3u files
└── profiles/
    └── kitt/                          # NEW: Hermes profile dir
        ├── config.yaml
        └── skills/
            ├── kitt-music-control.md
            └── kitt-tts-workflow.md
```

---

## Kanban Tasks

| Task | Assignee | Description |
|------|---------|-------------|
| Pi MCP music server | admin | Ensure `mpc` accessible via SSH, playlists in place |
| Hermes profile setup | admin | Create `~/.hermes/profiles/kitt/` |
| Skills + Telegram DM wiring | coder | Wire `kitt` profile to Telegram, load skills |
| TTS dual-path (Telegram + spool) | coder | Implement edge-tts → send_message + spool write |
| Music control skill | coder | SSH + mpc skill, playlist discovery |

---

## Not in scope

- Voice / STT input (text only)
- Music library management on Pi (playlists are predefined)
- Auto-deploy for the profile (daemon management)
- Multi-user support
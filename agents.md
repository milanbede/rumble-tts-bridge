# agents.md — KITT

## Profile Assignments

### coder
Implements all Python scripts: `tts-player.py`, `kitt-watcher.py`, `kick-watcher.py`. Writes systemd service files and launchd plists.

### admin
Installs system dependencies on RPI (mosquitto, mpc, mpd, edge-tts, paho-mqtt, KickApi). Sets up the Hermes `kitt` profile. Configures Telegram integration. Creates music directory structure on RPI.

---

## Task Routing Table

| Task | Profile | Location |
|------|---------|----------|
| mosquitto install + config | admin | RPI |
| edge-tts, paho-mqtt, KickApi install | admin | RPI |
| mpc + mpd install | admin | RPI |
| Music + playlists dir structure | admin | RPI |
| Bluetooth speaker verify paired | admin | RPI |
| `tts-player.py` implementation | coder | RPI |
| systemd service for tts-player | coder | RPI |
| `kitt-watcher.py` implementation | coder | MacBook |
| launchd plist for kitt-watcher | coder | MacBook |
| `kick-watcher.py` implementation | coder | RPI |
| systemd service for kick-watcher | coder | RPI |
| Hermes `kitt` profile setup | admin | MacBook |
| Telegram integration | admin | MacBook |
| SSH default remote to RPI | admin | MacBook |

---

## Escalation Protocol

1. Coder attempts a task.
2. If coder fails the same task 3 times, escalate — route to appropriate specialist.
3. Architect reviews all PRs before merge.

---

## Commit Convention

```
<type>: <short description>

[<optional body>]
```

Types: `feat`, `fix`, `test`, `docs`, `chore`

---

## Service Management

- RPI services: `systemd`
- MacBook services: `launchd`
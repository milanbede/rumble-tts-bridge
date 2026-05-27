# agents.md — rumble-tts-bridge

## Profile Assignments

### coder
Default implementer for all code tasks. Python, shell scripts, YAML configs.

### senior-coder
Escalation path. Used when `coder` fails a task 3 times. Handles harder architectural problems, edge cases, and performance-sensitive code.

### devops
Pi Zero OS setup, system deps, Bluetooth stack, bluez-alsa compilation, ALSA config, service management (systemd), network config.

### admin
Environment config, dependency installation, key management, host setup.

---

## Task Routing Table

| Task | Profile | Notes |
|------|---------|-------|
| TTS server scaffold + config | coder | |
| StateStore implementation + tests | coder | |
| Rumble poller implementation + tests | coder | |
| edge-tts wrapper + tests | coder | |
| HTTP server + tests | coder | |
| TTS server main + wiring | coder | |
| Pi client scaffold + config | coder | |
| TTSPlayer implementation + tests | coder | |
| Pi client main + bt-bridge script | coder | |
| Kick webhook server scaffold + config | coder | |
| Kick webhook signature verification + tests | coder | |
| Kick event mapping + tests | coder | |
| Kick OAuth token management + tests | coder | |
| Kick webhook server main + wiring | coder | |
| README | editor | |
| Obsidian note | archivist | |
| Specs | architect | |
| DevOps setup (Pi Zero OS, BT, bluez-alsa) | devops | |
| Admin tasks (dep install, key mgmt) | admin | |

---

## Escalation Protocol

1. Coder attempts a task.
2. If coder fails the same task 3 times (checked via task attempt counter), escalate to `senior-coder`.
3. Senior-coder gets full context: what was tried, what failed, error logs.
4. Senior-coder implements and commits directly.

---

## Review Gates

Every code task passes through two gates before completion:

**Gate 1 — Spec Compliance Review (coder reviews own work)**
- Does the code match the spec's exact requirements?
- File paths, function signatures, behavior — all verified.
- If non-compliant: fix, re-review, repeat.

**Gate 2 — Code Quality Review (architect reviews)**
- Style, error handling, naming, test coverage, security.
- If critical issues: fix, re-review, repeat.

---

## Commit Convention

All commits from coders use this format:
```
<type>: <short description>

<optional body with details>
```

Types: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`

Commits happen after each task's Gate 2 passes.

---

## State Assumptions

- Repo cloned at `/tmp/rumble-tts-bridge` for all work
- MacBook side: `tts-server/` directory
- Pi Zero side: `pi-client/` directory
- Tests in `tests/` parallel to each component
- Config files: `*.example.yaml` (committed), `config.yaml` (gitignored)
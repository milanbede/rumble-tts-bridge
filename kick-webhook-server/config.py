"""Config loading for kick-webhook-server."""

import yaml


REQUIRED_SECTIONS = ["kick", "server", "tts", "events"]

REQUIRED_KEYS = [
    "kick",
    "kick.oauth_token",
    "kick.client_id",
    "kick.client_secret",
    "kick.broadcaster_user_id",
    "kick.public_key_pem",
    "server",
    "server.host",
    "server.port",
    "server.spool_dir",
    "tts",
    "tts.voice",
    "tts.rate",
    "tts.volume",
    "events.channel.followed",
    "events.channel.subscription.new",
    "events.channel.subscription.gifts",
    "events.channel.subscription.renewal",
    "events.chat.message.sent",
]


def _get_nested(cfg: dict, key: str):
    parts = key.split(".")
    node = cfg
    for part in parts:
        node = node[part]
    if node is None:
        raise KeyError(key)
    return node


def _flatten_events(events_section: dict) -> dict:
    result = {}

    def _recurse(obj, prefix):
        if isinstance(obj, dict):
            for k, v in obj.items():
                new_key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    _recurse(v, new_key)
                else:
                    result[new_key] = v

    _recurse(events_section, "")
    return result


def load_config(path: str) -> dict:
    with open(path, "r") as f:
        cfg = yaml.safe_load(f)

    for section in REQUIRED_SECTIONS:
        if section not in cfg:
            raise KeyError(section)

    events_raw = cfg.get("events", {})
    if isinstance(events_raw, dict) and any("." in str(k) for k in events_raw):
        pass
    elif isinstance(events_raw, dict):
        cfg["events"] = _flatten_events(events_raw)

    events = cfg.get("events", {})

    for key in REQUIRED_KEYS:
        section = key.split(".")[0]
        if section == "events":
            event_key = key[len("events."):]
            if event_key not in events:
                raise KeyError(key)
        else:
            try:
                _get_nested(cfg, key)
            except KeyError:
                raise KeyError(key)

    return cfg
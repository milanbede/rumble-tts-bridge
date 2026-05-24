"""tts-server entry point — wires RumblePoller, TTSEngine, and HTTP server."""

import argparse
import logging
import sys

from config import load_config
from poller import Event, RumblePoller
from server import make_app
from state import StateStore
from tts import TTSEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def _on_event(tts: TTSEngine, event):
    """Callback invoked by RumblePoller for each new event."""
    log.info("Event received: %s", event)
    mp3_path = tts.speak(event.text)
    log.info("MP3 written: %s", mp3_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="tts-server")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: config.yaml)",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    log.info("Config loaded from %s", args.config)

    spool_dir = config["server"]["spool_dir"]
    state = StateStore(spool_dir)
    log.info("StateStore initialised at %s", spool_dir)

    tts_config = config["tts"]
    tts = TTSEngine(
        spool_dir=spool_dir,
        voice=tts_config["voice"],
        rate=tts_config["rate"],
        volume=tts_config["volume"],
    )
    log.info("TTSEngine ready (voice=%s, rate=%s, volume=%s)",
             tts.voice, tts.rate, tts.volume)

    rumble_config = config["rumble"]
    rumble_events = {k: config["events"].get(k, False) for k in config["events"]}
    poller = RumblePoller(
        api_url=rumble_config["api_url"],
        api_key=rumble_config["api_key"],
        state=state,
        config={**rumble_config, **rumble_events},
    )
    log.info("RumblePoller ready (api_url=%s)", rumble_config["api_url"])

    server_config = config["server"]
    httpd = make_app(
        spool_dir=spool_dir,
        host=server_config["host"],
        port=server_config["port"],
    )
    log.info("HTTP server started on %s:%s", server_config["host"], server_config["port"])

    # Blocking loop — run() never returns
    poller.run(lambda event: _on_event(tts, event))


if __name__ == "__main__":
    main()
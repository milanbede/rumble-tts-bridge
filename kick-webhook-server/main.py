"""kick-webhook-server entry point."""

import argparse
import sys

from config import load_config
from oauth import get_valid_token
from state import StateStore
from tts_speaker import get_or_create_player

from app import run_server


def main() -> None:
    parser = argparse.ArgumentParser(description="kick-webhook-server")
    parser.add_argument(
        "--config",
        required=True,
        help="Path to YAML config file",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)

    # Bootstrap StateStore
    spool_dir = cfg["server"]["spool_dir"]
    state_store = StateStore(spool_dir)

    # Bootstrap OAuth token
    get_valid_token(
        cfg["kick"]["client_id"],
        cfg["kick"]["client_secret"],
        spool_dir,
    )

    # Bootstrap TTS player
    get_or_create_player(cfg["tts"])

    print(f"kick-webhook-server starting on {cfg['server']['host']}:{cfg['server']['port']}")
    run_server(cfg)


if __name__ == "__main__":
    main()
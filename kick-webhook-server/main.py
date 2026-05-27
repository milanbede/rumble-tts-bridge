"""kick-webhook-server entry point."""

import argparse
import sys

from config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="kick-webhook-server")
    parser.add_argument(
        "--config",
        required=True,
        help="Path to YAML config file",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    print(f"kick-webhook-server starting on {cfg['server']['host']}:{cfg['server']['port']}")


if __name__ == "__main__":
    main()
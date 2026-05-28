"""Tests for kick-webhook-server main entry point (R7)."""

import sys
from unittest.mock import MagicMock, patch

import pytest

import main


@pytest.fixture
def minimal_config(tmp_path):
    """Return a minimal config dict with all required keys."""
    return {
        "kick": {
            "oauth_token": "initial_token",
            "client_id": "test_client",
            "client_secret": "test_secret",
            "broadcaster_user_id": 123456,
            "public_key_pem": "-----BEGIN PUBLIC KEY-----\nMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAETest\n-----END PUBLIC KEY-----\n",
        },
        "server": {
            "host": "127.0.0.1",
            "port": 9000,
            "spool_dir": str(tmp_path),
        },
        "tts": {
            "voice": "en-US-JennyNeural",
            "rate": "+10%",
            "volume": "+20%",
        },
        "events": {
            "channel.followed": True,
            "channel.subscription.new": True,
            "channel.subscription.gifts": True,
            "channel.subscription.renewal": False,
            "chat.message.sent": False,
        },
    }


class TestMain:
    def test_loads_config_from_argv(self, minimal_config, tmp_path):
        """main() calls load_config with the --config argument."""
        cfg_path = tmp_path / "config.yaml"
        import yaml
        with open(cfg_path, "w") as f:
            yaml.dump(minimal_config, f)

        with patch.object(main, "load_config", return_value=minimal_config) as mock_load:
            with patch.object(main, "StateStore"):
                with patch.object(main, "get_or_create_player"):
                    with patch.object(main, "get_valid_token", return_value="tok"):
                        with patch.object(main, "run_server"):
                            sys.argv = ["kick-webhook-server", "--config", str(cfg_path)]
                            main.main()
                            mock_load.assert_called_once_with(str(cfg_path))

    def test_initializes_state_store_with_spool_dir(self, minimal_config, tmp_path):
        """StateStore is created with the spool_dir from config."""
        cfg_path = tmp_path / "config.yaml"
        import yaml
        with open(cfg_path, "w") as f:
            yaml.dump(minimal_config, f)

        with patch.object(main, "load_config", return_value=minimal_config):
            with patch.object(main, "StateStore", MagicMock()) as mock_state_cls:
                with patch.object(main, "get_or_create_player"):
                    with patch.object(main, "get_valid_token", return_value="tok"):
                        with patch.object(main, "run_server"):
                            sys.argv = ["kick-webhook-server", "--config", str(cfg_path)]
                            main.main()
                            mock_state_cls.assert_called_once_with(str(tmp_path))

    def test_initializes_tts_player(self, minimal_config, tmp_path):
        """TTS player is initialized with voice/rate/volume from config."""
        cfg_path = tmp_path / "config.yaml"
        import yaml
        with open(cfg_path, "w") as f:
            yaml.dump(minimal_config, f)

        with patch.object(main, "load_config", return_value=minimal_config):
            with patch.object(main, "StateStore"):
                with patch.object(main, "get_or_create_player", MagicMock()) as mock_get_player:
                    with patch.object(main, "get_valid_token", return_value="tok"):
                        with patch.object(main, "run_server"):
                            sys.argv = ["kick-webhook-server", "--config", str(cfg_path)]
                            main.main()
                            mock_get_player.assert_called_once_with(minimal_config["tts"])

    def test_fetches_oauth_token_at_startup(self, minimal_config, tmp_path):
        """get_valid_token is called at startup to bootstrap the OAuth token."""
        cfg_path = tmp_path / "config.yaml"
        import yaml
        with open(cfg_path, "w") as f:
            yaml.dump(minimal_config, f)

        with patch.object(main, "load_config", return_value=minimal_config):
            with patch.object(main, "StateStore"):
                with patch.object(main, "get_or_create_player"):
                    with patch.object(
                        main, "get_valid_token", return_value="bootstrapped_token"
                    ) as mock_get_token:
                        with patch.object(main, "run_server"):
                            sys.argv = ["kick-webhook-server", "--config", str(cfg_path)]
                            main.main()
                            mock_get_token.assert_called_once()

    def test_runs_flask_app(self, minimal_config, tmp_path):
        """run_server is called with the full config after bootstrapping."""
        cfg_path = tmp_path / "config.yaml"
        import yaml
        with open(cfg_path, "w") as f:
            yaml.dump(minimal_config, f)

        with patch.object(main, "load_config", return_value=minimal_config):
            with patch.object(main, "StateStore"):
                with patch.object(main, "get_or_create_player"):
                    with patch.object(main, "get_valid_token", return_value="tok"):
                        with patch.object(main, "run_server", MagicMock()) as mock_run:
                            sys.argv = ["kick-webhook-server", "--config", str(cfg_path)]
                            main.main()
                            mock_run.assert_called_once_with(minimal_config)
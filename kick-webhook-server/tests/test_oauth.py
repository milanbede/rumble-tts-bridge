"""Tests for kick-webhook-server OAuth2 token management (R6)."""

import json
import requests
import time
from unittest.mock import patch, MagicMock

import pytest

import oauth


@pytest.fixture
def spool_dir(tmp_path):
    return str(tmp_path)


class TestRefreshOAuthToken:
    def test_posts_to_correct_url(self, spool_dir):
        """refresh_oauth_token() POSTs to the Kick token endpoint."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_token_abc",
            "expires_in": 3600,
        }

        with patch("oauth.requests.post", return_value=mock_response) as mock_post:
            oauth.refresh_oauth_token("my_client", "my_secret", spool_dir)
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            assert args[0] == "https://id.kick.com/oauth/token"
            assert kwargs["data"]["grant_type"] == "client_credentials"
            assert kwargs["data"]["client_id"] == "my_client"
            assert kwargs["data"]["client_secret"] == "my_secret"
            assert kwargs["data"]["scope"] == "application:events"

    def test_returns_token_and_expiry(self, spool_dir):
        """Response is parsed and returned as access_token + expires_at."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "token_xyz",
            "expires_in": 7200,
        }

        with patch("oauth.requests.post", return_value=mock_response):
            result = oauth.refresh_oauth_token("c", "s", spool_dir)

        assert result["access_token"] == "token_xyz"
        assert isinstance(result["expires_at"], float)
        # expires_at should be approximately now + expires_in
        assert abs(result["expires_at"] - (time.time() + 7200)) < 5

    def test_persists_token_to_disk(self, spool_dir):
        """Refreshed token is written to kick_oauth_state.json in spool_dir."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "disk_token", "expires_in": 3600}

        with patch("oauth.requests.post", return_value=mock_response):
            oauth.refresh_oauth_token("c", "s", spool_dir)

        state_file = f"{spool_dir}/kick_oauth_state.json"
        assert oauth.Path(state_file).exists()
        stored = json.loads(open(state_file).read())
        assert stored["access_token"] == "disk_token"

    def test_raises_runtime_on_http_error(self, spool_dir):
        """Non-200 response raises RuntimeError with the status code."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "invalid credentials"

        with patch("oauth.requests.post", return_value=mock_response):
            with pytest.raises(RuntimeError, match="401"):
                oauth.refresh_oauth_token("c", "s", spool_dir)

    def test_raises_runtime_on_network_error(self, spool_dir):
        """Network failure raises RuntimeError."""
        with patch("oauth.requests.post", side_effect=requests.RequestException("network fail")):
            with pytest.raises(RuntimeError, match="OAuth token request failed"):
                oauth.refresh_oauth_token("c", "s", spool_dir)


class TestGetValidToken:
    def test_returns_cached_token_if_not_expired(self, spool_dir):
        """get_valid_token() returns current_token without hitting network if not expired."""
        not_expired = {"access_token": "cached_tok", "expires_at": time.time() + 300}

        with patch.object(oauth, "_read_token_state", return_value=not_expired):
            with patch.object(oauth, "refresh_oauth_token") as mock_refresh:
                token = oauth.get_valid_token("c", "s", spool_dir, current_token="cached_tok")
                assert token == "cached_tok"
                mock_refresh.assert_not_called()

    def test_refreshes_if_token_missing(self, spool_dir):
        """get_valid_token() calls refresh if no cached token exists."""
        with patch.object(oauth, "_read_token_state", return_value=None):
            with patch.object(
                oauth, "refresh_oauth_token", return_value={"access_token": "fresh", "expires_at": 0}
            ) as mock_refresh:
                token = oauth.get_valid_token("c", "s", spool_dir)
                mock_refresh.assert_called_once_with("c", "s", spool_dir)
                assert token == "fresh"

    def test_refreshes_if_token_expired(self, spool_dir):
        """get_valid_token() refreshes when cached token is past the buffer window."""
        expired = {"access_token": "expired_tok", "expires_at": time.time() - 120}

        with patch.object(oauth, "_read_token_state", return_value=expired):
            with patch.object(
                oauth, "refresh_oauth_token", return_value={"access_token": "new_tok", "expires_at": 0}
            ) as mock_refresh:
                token = oauth.get_valid_token("c", "s", spool_dir)
                assert token == "new_tok"
                mock_refresh.assert_called_once()

    def test_raises_runtime_if_refresh_fails(self, spool_dir):
        """Failed refresh propagates as RuntimeError."""
        with patch.object(oauth, "_read_token_state", return_value=None):
            with patch.object(
                oauth, "refresh_oauth_token", side_effect=RuntimeError("bad creds")
            ):
                with pytest.raises(RuntimeError, match="bad creds"):
                    oauth.get_valid_token("c", "s", spool_dir)
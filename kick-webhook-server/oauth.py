"""OAuth2 token management for Kick — client_credentials flow."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

TOKEN_URL = "https://id.kick.com/oauth/token"
_TOKEN_BUFFER_SECONDS = 60  # refresh 60s before expiry


def _state_file_path(spool_dir: str) -> Path:
    return Path(spool_dir) / "kick_oauth_state.json"


def refresh_oauth_token(client_id: str, client_secret: str, spool_dir: str) -> dict[str, Any]:
    """Fetch a new access token from Kick OAuth and persist it to spool_dir.

    Args:
        client_id: Kick OAuth client_id.
        client_secret: Kick OAuth client_secret.
        spool_dir: Directory to persist the token state file.

    Returns:
        Dict with keys ``access_token`` and ``expires_at`` (unix timestamp).

    Raises:
        RuntimeError: If the token request fails (non-200 response or network error).
    """
    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "application:events",
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"OAuth token request failed: {exc}") from exc

    if response.status_code != 200:
        raise RuntimeError(
            f"OAuth token request failed with status {response.status_code}: {response.text}"
        )

    token_data = response.json()
    access_token = token_data.get("access_token")
    expires_in = token_data.get("expires_in", 3600)

    if not access_token:
        raise RuntimeError(f"OAuth response missing access_token: {token_data}")

    result = {
        "access_token": access_token,
        "expires_at": time.time() + expires_in,
    }

    # Persist to state file alongside StateStore's state.json
    state_path = _state_file_path(spool_dir)
    state_path.write_text(json.dumps(result))

    return result


def get_valid_token(
    client_id: str, client_secret: str, spool_dir: str, current_token: str | None = None
) -> str:
    """Return a valid OAuth access token, refreshing if necessary.

    Args:
        client_id: Kick OAuth client_id.
        client_secret: Kick OAuth client_secret.
        spool_dir: Directory where the OAuth state file is stored.
        current_token: If provided, and not expired (with 60s buffer), return it directly
            without hitting the network. Pass the currently-loaded token here to avoid
            a redundant refresh on every call.

    Returns:
        A valid access token string.

    Raises:
        RuntimeError: If token refresh fails.
    """
    state_path = _state_file_path(spool_dir)

    # Check in-memory current_token first
    if current_token is not None:
        token_info = _read_token_state(state_path)
        if token_info is not None:
            if time.time() < (token_info["expires_at"] - _TOKEN_BUFFER_SECONDS):
                return token_info["access_token"]

    # Try loading from disk
    token_info = _read_token_state(state_path)
    if token_info is not None:
        if time.time() < (token_info["expires_at"] - _TOKEN_BUFFER_SECONDS):
            return token_info["access_token"]

    # Refresh
    new_token = refresh_oauth_token(client_id, client_secret, spool_dir)
    return new_token["access_token"]


def _read_token_state(state_path: Path) -> dict[str, Any] | None:
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
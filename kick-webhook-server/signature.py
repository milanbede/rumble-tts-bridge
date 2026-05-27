"""ECDSA secp256k1 signature verification for Kick webhooks.

Kick signs the raw request body with ECDSA secp256k1. The signature header
format is: ``t={timestamp},v1={base64_signature}``. The signed payload is
``timestamp + "." + raw_body_bytes``.
"""

import base64
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend
import cryptography.exceptions

# Maximum age of a webhook timestamp before it's considered replay.
_REPLAY_WINDOW_SECONDS = 5 * 60


def verify_signature(payload_bytes: bytes, signature_header: str, public_key_pem: str) -> bool:
    """Verify a Kick webhook ECDSA signature.

    Args:
        payload_bytes: Raw request body bytes (use ``request.get_data()`` in Flask).
        signature_header: Value of the ``X-Kick-Signature`` header.
            Format: ``t={timestamp},v1={base64_signature}``.
        public_key_pem: PEM-encoded ECDSA public key (secp256k1).

    Returns:
        True if the signature is valid; False otherwise.

    Raises:
        ValueError: If the public key PEM is malformed or not a valid EC key.
    """
    if not signature_header:
        return False

    try:
        # Parse the signature header
        parts = dict(p.split("=", 1) for p in signature_header.split(",") if "=" in p)
        timestamp = parts.get("t", "")
        sig_b64 = parts.get("v1", "")
        if not timestamp or not sig_b64:
            return False
    except Exception:
        return False

    # Replay protection: reject timestamps older than 5 minutes (allow 60s future drift)
    try:
        ts_int = int(timestamp)
    except (ValueError, TypeError):
        return False
    age = time.time() - ts_int
    if age > _REPLAY_WINDOW_SECONDS or age < -60:
        return False

    # Load public key
    try:
        public_key = serialization.load_pem_public_key(
            public_key_pem.encode("utf-8"),
            backend=default_backend(),
        )
    except Exception as exc:
        raise ValueError(f"Invalid public key PEM: {exc}") from exc

    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise ValueError("Public key is not an EC key")

    if public_key.curve.name != "secp256k1":
        raise ValueError(f"Expected secp256k1 curve, got {public_key.curve.name}")

    # Decode signature
    try:
        sig_bytes = base64.b64decode(sig_b64)
    except Exception:
        return False

    # Signed message: timestamp + "." + payload_bytes
    signed_data = f"{timestamp}.".encode("utf-8") + payload_bytes

    # Verify ECDSA signature using SHA256
    try:
        public_key.verify(sig_bytes, signed_data, ec.ECDSA(hashes.SHA256()))
        return True
    except cryptography.exceptions.InvalidSignature:
        return False
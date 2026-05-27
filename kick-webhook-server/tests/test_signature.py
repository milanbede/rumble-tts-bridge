"""Tests for kick-webhook-server ECDSA signature verification."""

import time

import pytest

from signature import verify_signature


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def generate_secp256k1_keypair():
    """Generate a secp256k1 key pair and return (private_pem, public_pem)."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization

    private_key = ec.generate_private_key(ec.SECP256K1(), default_backend())
    public_key = private_key.public_key()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def sign_data(private_pem: bytes, timestamp: str, payload: bytes) -> str:
    """Sign timestamp.payload_bytes with ECDSA secp256k1, return base64 signature."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.backends import default_backend
    import base64

    private_key = serialization.load_pem_private_key(
        private_pem, password=None, backend=default_backend()
    )
    signed_data = f"{timestamp}.".encode("utf-8") + payload
    der_sig = private_key.sign(signed_data, ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(der_sig).decode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def keypair():
    """A fresh secp256k1 keypair for each test."""
    private_pem, public_pem = generate_secp256k1_keypair()
    return private_pem, public_pem


@pytest.fixture
def payload():
    return b'{"event":"channel.followed","data":{"user":{"username":"testuser"}}}'


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestVerifySignature:
    """Tests for verify_signature()."""

    def test_valid_signature_returns_true(self, keypair, payload):
        """A signature generated with the matching private key passes."""
        private_pem, public_pem = keypair
        timestamp = str(int(time.time()))
        sig_b64 = sign_data(private_pem, timestamp, payload)
        header = f"t={timestamp},v1={sig_b64}"

        result = verify_signature(payload, header, public_pem.decode())
        assert result is True

    def test_tampered_payload_returns_false(self, keypair, payload):
        """Modifying any byte of the payload invalidates the signature."""
        private_pem, public_pem = keypair
        timestamp = str(int(time.time()))
        sig_b64 = sign_data(private_pem, timestamp, payload)
        header = f"t={timestamp},v1={sig_b64}"

        tampered = payload.replace(b"testuser", b"hacker123")
        assert tampered != payload

        result = verify_signature(tampered, header, public_pem.decode())
        assert result is False

    def test_missing_signature_header_returns_false(self, keypair, payload):
        """Empty or malformed X-Kick-Signature header is rejected."""
        _, public_pem = keypair

        assert verify_signature(payload, "", public_pem.decode()) is False
        assert verify_signature(payload, "t=12345", public_pem.decode()) is False  # no v1
        assert verify_signature(payload, "v1=abc", public_pem.decode()) is False  # no t
        assert verify_signature(payload, "garbage", public_pem.decode()) is False

    def test_invalid_public_key_pem_raises_value_error(self, keypair, payload):
        """Passing a malformed PEM raises ValueError."""
        _, _ = keypair  # suppress unused warning
        current_ts = str(int(time.time()))

        bad_pems = [
            "not a pem at all",
            "-----BEGIN PUBLIC KEY-----\ntruncated\n-----END PUBLIC KEY-----",
            "[REDACTED PRIVATE KEY]",
            "",
        ]
        for bad in bad_pems:
            with pytest.raises(ValueError):
                verify_signature(payload, f"t={current_ts},v1=abc", bad)

    def test_old_timestamp_returns_false(self, keypair, payload):
        """A signature whose timestamp is older than 5 minutes is rejected."""
        private_pem, public_pem = keypair
        old_timestamp = str(int(time.time()) - 400)  # 6+ minutes ago
        sig_b64 = sign_data(private_pem, old_timestamp, payload)
        header = f"t={old_timestamp},v1={sig_b64}"

        result = verify_signature(payload, header, public_pem.decode())
        assert result is False

    def test_timestamp_within_5min_succeeds(self, keypair, payload):
        """Timestamp up to 4 minutes old should still be valid."""
        private_pem, public_pem = keypair
        # 3 minutes ago — well within the 5-minute window
        recent_timestamp = str(int(time.time()) - 180)
        sig_b64 = sign_data(private_pem, recent_timestamp, payload)
        header = f"t={recent_timestamp},v1={sig_b64}"

        result = verify_signature(payload, header, public_pem.decode())
        assert result is True

    def test_wrong_public_key_returns_false(self, keypair, payload):
        """Signing with one key and verifying with a different key fails."""
        private_pem, _ = keypair
        # Generate a completely different keypair
        _, wrong_public_pem = generate_secp256k1_keypair()

        timestamp = str(int(time.time()))
        sig_b64 = sign_data(private_pem, timestamp, payload)
        header = f"t={timestamp},v1={sig_b64}"

        result = verify_signature(payload, header, wrong_public_pem.decode())
        assert result is False
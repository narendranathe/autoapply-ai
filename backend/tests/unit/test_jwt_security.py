"""
Regression tests for JWT algorithm-confusion attacks.

`app.dependencies.get_current_user` pins ``algorithms=["RS256"]`` when
calling ``jwt.decode``. These tests craft tokens that would only be
accepted if that allowlist were loosened, and assert each one is
rejected. Any future change that broadens the algorithm allowlist
(e.g. adds HS256, or accepts a token whose header says ``alg=none``)
will break at least one of these tests.

The tests call ``jwt.decode`` directly with the same arguments
``dependencies.py`` uses, so they exercise the exact security boundary
without needing the full FastAPI request lifecycle.
"""

import base64
import hashlib
import hmac
import json
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import JWTError, jwt

ALGORITHMS = ["RS256"]
GOOD_KID = "clerk-good-kid"


def _b64url(data: bytes | str) -> str:
    """Encode bytes/str as base64url without padding (RFC 7515)."""
    if isinstance(data, str):
        data = data.encode()
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _int_to_b64url(value: int) -> str:
    length = (value.bit_length() + 7) // 8
    return _b64url(value.to_bytes(length, "big"))


@pytest.fixture(scope="module")
def rsa_keypair() -> tuple[rsa.RSAPrivateKey, bytes]:
    """A fresh RSA-2048 keypair, returning (private_key, public_pem)."""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv, pub_pem


@pytest.fixture(scope="module")
def jwks(rsa_keypair: tuple[rsa.RSAPrivateKey, bytes]) -> dict[str, Any]:
    """A JWKS dict mirroring Clerk's ``/.well-known/jwks.json`` shape."""
    priv, _ = rsa_keypair
    nums = priv.public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "kid": GOOD_KID,
                "alg": "RS256",
                "n": _int_to_b64url(nums.n),
                "e": _int_to_b64url(nums.e),
            }
        ]
    }


@pytest.fixture(scope="module")
def signing_pem(rsa_keypair: tuple[rsa.RSAPrivateKey, bytes]) -> bytes:
    """PEM-encoded private key suitable for ``jwt.encode``."""
    priv, _ = rsa_keypair
    return priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def test_valid_rs256_token_decodes(jwks: dict[str, Any], signing_pem: bytes) -> None:
    """Sanity: a correctly-signed RS256 token must still decode. Without
    this baseline the negative tests below could pass trivially."""
    token = jwt.encode(
        {"sub": "user_legit"},
        signing_pem,
        algorithm="RS256",
        headers={"kid": GOOD_KID},
    )
    payload = jwt.decode(token, jwks, algorithms=ALGORITHMS)
    assert payload["sub"] == "user_legit"


def test_hs256_confusion_rejected(
    jwks: dict[str, Any], rsa_keypair: tuple[rsa.RSAPrivateKey, bytes]
) -> None:
    """Classic algorithm-confusion: attacker signs an HS256 token using
    the RSA public-key PEM as the HMAC secret. python-jose refuses to
    forge this token via ``jwt.encode`` (it blocks asymmetric keys from
    being used as HMAC secrets) so the token is crafted by hand."""
    _, pub_pem = rsa_keypair
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT", "kid": GOOD_KID}))
    payload = _b64url(json.dumps({"sub": "attacker"}))
    signing_input = f"{header}.{payload}".encode()
    sig = hmac.new(pub_pem, signing_input, hashlib.sha256).digest()
    token = f"{header}.{payload}.{_b64url(sig)}"

    with pytest.raises(JWTError) as excinfo:
        jwt.decode(token, jwks, algorithms=ALGORITHMS)
    assert "alg" in str(excinfo.value).lower()


def test_alg_none_rejected(jwks: dict[str, Any]) -> None:
    """An ``alg=none`` token with an empty signature must never be
    accepted, even though it carries a known-good ``kid``."""
    header = _b64url(json.dumps({"alg": "none", "typ": "JWT", "kid": GOOD_KID}))
    payload = _b64url(json.dumps({"sub": "attacker"}))
    token = f"{header}.{payload}."

    with pytest.raises(JWTError) as excinfo:
        jwt.decode(token, jwks, algorithms=ALGORITHMS)
    assert "alg" in str(excinfo.value).lower()


def test_kid_swap_rejected(jwks: dict[str, Any]) -> None:
    """A token signed with an attacker-controlled RSA key but bearing a
    legitimate ``kid`` must fail signature verification: the JWKS lookup
    finds the real public key, which cannot verify the foreign signature."""
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attacker_pem = attacker.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    token = jwt.encode(
        {"sub": "attacker"},
        attacker_pem,
        algorithm="RS256",
        headers={"kid": GOOD_KID},
    )

    with pytest.raises(JWTError):
        jwt.decode(token, jwks, algorithms=ALGORITHMS)


def test_missing_alg_rejected(jwks: dict[str, Any]) -> None:
    """A header with no ``alg`` field must be rejected by the JWS parser
    before any key material is consulted."""
    header = _b64url(json.dumps({"typ": "JWT", "kid": GOOD_KID}))
    payload = _b64url(json.dumps({"sub": "attacker"}))
    token = f"{header}.{payload}."

    with pytest.raises(JWTError):
        jwt.decode(token, jwks, algorithms=ALGORITHMS)


def test_empty_alg_rejected(jwks: dict[str, Any]) -> None:
    """An empty-string ``alg`` is the close cousin of a missing one and
    must be rejected for the same reason."""
    header = _b64url(json.dumps({"alg": "", "typ": "JWT", "kid": GOOD_KID}))
    payload = _b64url(json.dumps({"sub": "attacker"}))
    token = f"{header}.{payload}."

    with pytest.raises(JWTError):
        jwt.decode(token, jwks, algorithms=ALGORITHMS)

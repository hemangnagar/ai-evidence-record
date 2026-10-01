"""Signed manifest for the datasheet, so it can be handed over and verified offline.

Lifted from corpuscle's signed-bundle module: a DSSE-style pre-authentication
encoding over canonical JSON, with a pluggable signer. The demo ships an HMAC
signer with a demo key because it needs no extra dependency. Production should
use the Ed25519 signer below (``pip install cryptography``) or an HSM-backed
signer behind the same two-method interface; the manifest format does not change.
"""

from __future__ import annotations

import base64
import hmac
import os
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from .ledger import canonical

PAYLOAD_TYPE = "application/vnd.aievidence.manifest+json"
DEMO_KEY_ENV = "AIEV_SIGNING_KEY"
DEMO_KEY = b"aievidence-demo-key-not-for-production"


def pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE pre-authentication encoding: binds the payload type to the bytes signed."""
    return b"DSSEv1 %d %s %d %s" % (len(payload_type), payload_type.encode(), len(payload), payload)


class Signer(Protocol):
    keyid: str
    alg: str

    def sign(self, data: bytes) -> bytes: ...

    def verify(self, data: bytes, sig: bytes) -> bool: ...


class HmacSigner:
    """Demo signer. Symmetric, so anyone who can verify can also forge; fine for a demo, not for an inspector."""

    alg = "hmac-sha256"

    def __init__(self, key: bytes, keyid: str = "demo-hmac"):
        self._key, self.keyid = key, keyid

    @classmethod
    def from_env(cls) -> HmacSigner:
        key = os.environ.get(DEMO_KEY_ENV)
        return cls(key.encode() if key else DEMO_KEY, "env-hmac" if key else "demo-hmac")

    def sign(self, data: bytes) -> bytes:
        return hmac.new(self._key, data, sha256).digest()

    def verify(self, data: bytes, sig: bytes) -> bool:
        return hmac.compare_digest(self.sign(data), sig)


class Ed25519Signer:
    """Production choice. Requires the ``cryptography`` package; imported lazily so the demo has no hard dependency."""

    alg = "ed25519"

    def __init__(self, key, keyid: str = "ed25519"):
        self._key, self.keyid = key, keyid

    @classmethod
    def generate(cls, keyid: str = "ed25519") -> Ed25519Signer:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        return cls(Ed25519PrivateKey.generate(), keyid)

    @classmethod
    def from_pem(cls, path: str | Path, keyid: str = "ed25519") -> Ed25519Signer:
        from cryptography.hazmat.primitives import serialization

        return cls(serialization.load_pem_private_key(Path(path).read_bytes(), password=None), keyid)

    def sign(self, data: bytes) -> bytes:
        return self._key.sign(data)

    def verify(self, data: bytes, sig: bytes) -> bool:
        from cryptography.exceptions import InvalidSignature

        try:
            self._key.public_key().verify(sig, data)
            return True
        except InvalidSignature:
            return False


def sign_manifest(manifest: dict, signer: Signer) -> dict:
    """Return a copy of ``manifest`` with a ``signature`` block over everything else."""
    body = {k: v for k, v in manifest.items() if k != "signature"}
    sig = signer.sign(pae(PAYLOAD_TYPE, canonical(body)))
    return {
        **body,
        "signature": {
            "alg": signer.alg,
            "keyid": signer.keyid,
            "payload_type": PAYLOAD_TYPE,
            "sig": base64.b64encode(sig).decode(),
        },
    }


def verify_manifest(manifest: dict, signer: Signer) -> bool:
    sig_block = manifest.get("signature") or {}
    body = {k: v for k, v in manifest.items() if k != "signature"}
    try:
        sig = base64.b64decode(sig_block.get("sig", ""))
    except ValueError:
        return False
    if sig_block.get("payload_type") != PAYLOAD_TYPE:
        return False
    return signer.verify(pae(PAYLOAD_TYPE, canonical(body)), sig)

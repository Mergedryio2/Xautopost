from __future__ import annotations

import json
import os
from typing import Any

import keyring
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEYRING_SERVICE = "Xautopost"
KEYRING_USER = "master_key"


def get_or_create_master_key() -> bytes:
    raw = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    if raw:
        return bytes.fromhex(raw)
    key = os.urandom(32)
    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key.hex())
    return key


class Crypto:
    """AES-GCM field encryption. Master key lives in OS keyring."""

    def __init__(self, key: bytes | None = None) -> None:
        self._aes = AESGCM(key or get_or_create_master_key())

    def encrypt(self, plaintext: bytes, aad: bytes | None = None) -> bytes:
        nonce = os.urandom(12)
        ct = self._aes.encrypt(nonce, plaintext, aad)
        return nonce + ct

    def decrypt(self, blob: bytes, aad: bytes | None = None) -> bytes:
        nonce, ct = blob[:12], blob[12:]
        return self._aes.decrypt(nonce, ct, aad)

    def encrypt_str(self, s: str) -> bytes:
        return self.encrypt(s.encode("utf-8"))

    def decrypt_str(self, blob: bytes) -> str:
        return self.decrypt(blob).decode("utf-8")

    def encrypt_json(self, obj: Any) -> bytes:
        return self.encrypt_str(json.dumps(obj))

    def decrypt_json(self, blob: bytes) -> Any:
        return json.loads(self.decrypt_str(blob))


_singleton: Crypto | None = None


def get_crypto() -> Crypto:
    global _singleton
    if _singleton is None:
        _singleton = Crypto()
    return _singleton

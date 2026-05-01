from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(passphrase: str) -> str:
    return _hasher.hash(passphrase)


def verify_password(stored_hash: str, passphrase: str) -> bool:
    try:
        return _hasher.verify(stored_hash, passphrase)
    except (VerifyMismatchError, InvalidHash):
        return False

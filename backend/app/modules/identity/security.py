from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# PasswordHasher memakai Argon2id dengan parameter default yang aman
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """True bila cocok. Hash rusak atau password salah selalu False."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True bila hash dibuat dengan parameter lama dan perlu diperbarui."""
    return _hasher.check_needs_rehash(password_hash)
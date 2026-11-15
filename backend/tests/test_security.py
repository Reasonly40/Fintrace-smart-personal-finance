from app.modules.identity.security import (
    hash_password,
    needs_rehash,
    verify_password,
)


def test_hash_is_argon2id_and_not_plaintext():
    password_hash = hash_password("Rahasia-Banget-123")
    assert password_hash.startswith("$argon2id$")
    assert "Rahasia" not in password_hash


def test_verify_correct_and_wrong_password():
    password_hash = hash_password("benar-123")
    assert verify_password("benar-123", password_hash) is True
    assert verify_password("salah-123", password_hash) is False


def test_same_password_gets_different_hashes():
    # Salt acak: dua hash dari password yang sama tidak boleh identik
    assert hash_password("sama-123") != hash_password("sama-123")


def test_verify_garbage_hash_returns_false():
    assert verify_password("apa-saja", "bukan-hash") is False


def test_fresh_hash_does_not_need_rehash():
    assert needs_rehash(hash_password("abc12345")) is False
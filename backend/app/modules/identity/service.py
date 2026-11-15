import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ConflictError, UnauthorizedError
from app.modules.identity.models import User, UserSession
from app.modules.identity.security import (
    hash_password,
    needs_rehash,
    verify_password,
)


class EmailAlreadyRegisteredError(ConflictError):
    code = "email_already_registered"
    message = "Email sudah terdaftar."


class InvalidCredentialsError(UnauthorizedError):
    code = "invalid_credentials"
    message = "Email atau password salah."


class NotAuthenticatedError(UnauthorizedError):
    code = "not_authenticated"
    message = "Anda belum masuk atau sesi sudah berakhir."


# Hash palsu: dipakai agar waktu respons login tetap mirip
# ketika email tidak ditemukan (mengurangi celah timing).
_DUMMY_HASH = hash_password("timing-equalizer-password")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def register_user(
    db: Session, *, email: str, password: str, full_name: str
) -> User:
    normalized = normalize_email(email)

    exists = db.execute(
        select(User.id).where(User.email == normalized)
    ).first()
    if exists is not None:
        raise EmailAlreadyRegisteredError()

    user = User(
        email=normalized,
        password_hash=hash_password(password),
        full_name=full_name,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        # Dua registrasi bersamaan: yang kalah balapan ditolak oleh
        # unique constraint database, bukan oleh pengecekan di atas.
        db.rollback()
        raise EmailAlreadyRegisteredError() from exc
    db.refresh(user)
    return user


def authenticate(db: Session, *, email: str, password: str) -> User:
    user = db.execute(
        select(User).where(User.email == normalize_email(email))
    ).scalar_one_or_none()

    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise InvalidCredentialsError()

    password_ok = verify_password(password, user.password_hash)
    if not password_ok or not user.is_active:
        raise InvalidCredentialsError()

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        db.commit()
    return user


def create_session(db: Session, user: User) -> str:
    """Buat sesi baru dan kembalikan token mentah (hanya dikirim sekali)."""
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC)
            + timedelta(days=settings.session_ttl_days),
        )
    )
    db.commit()
    return token


def revoke_session(db: Session, token: str) -> None:
    db.execute(
        update(UserSession)
        .where(
            UserSession.token_hash == hash_token(token),
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    db.commit()


def get_user_by_session_token(db: Session, token: str) -> User | None:
    """User pemilik sesi yang valid (belum dicabut, belum kedaluwarsa)."""
    return db.execute(
        select(User)
        .join(UserSession, UserSession.user_id == User.id)
        .where(
            UserSession.token_hash == hash_token(token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > datetime.now(UTC),
            User.is_active.is_(True),
        )
    ).scalar_one_or_none()
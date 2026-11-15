from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.modules.identity.models import User
from app.modules.identity.security import hash_password


class EmailAlreadyRegisteredError(ConflictError):
    code = "email_already_registered"
    message = "Email sudah terdaftar."


def normalize_email(email: str) -> str:
    return email.strip().lower()


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
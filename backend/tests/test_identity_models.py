import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.identity.models import User, UserSession


def make_user(email: str = "budi@example.com") -> User:
    return User(
        email=email, password_hash="hash-placeholder", full_name="Budi"
    )


def future() -> datetime:
    return datetime.now(UTC) + timedelta(days=7)


def test_user_gets_uuid_and_defaults(db_session):
    user = make_user()
    db_session.add(user)
    db_session.flush()
    db_session.refresh(user)

    assert isinstance(user.id, uuid.UUID)
    assert user.is_active is True
    assert user.created_at.tzinfo is not None
    assert user.email_verified_at is None


def test_email_must_be_unique(db_session):
    db_session.add(make_user("a@example.com"))
    db_session.flush()

    db_session.add(make_user("a@example.com"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_email_must_be_lowercase(db_session):
    db_session.add(make_user("Budi@Example.com"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_session_token_hash_must_be_unique(db_session):
    user = make_user()
    db_session.add(user)
    db_session.flush()

    db_session.add(
        UserSession(user_id=user.id, token_hash="a" * 64, expires_at=future())
    )
    db_session.flush()

    db_session.add(
        UserSession(user_id=user.id, token_hash="a" * 64, expires_at=future())
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_session_requires_existing_user(db_session):
    db_session.add(
        UserSession(
            user_id=uuid.uuid4(), token_hash="b" * 64, expires_at=future()
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_deleting_user_deletes_sessions(db_session):
    user = make_user()
    db_session.add(user)
    db_session.flush()
    db_session.add(
        UserSession(user_id=user.id, token_hash="c" * 64, expires_at=future())
    )
    db_session.flush()

    db_session.delete(user)
    db_session.flush()

    remaining = db_session.execute(
        select(UserSession).where(UserSession.user_id == user.id)
    ).scalars().all()
    assert remaining == []
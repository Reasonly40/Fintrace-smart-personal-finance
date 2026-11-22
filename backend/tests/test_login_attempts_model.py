import uuid

from app.modules.identity.models import LoginAttempt


def test_login_attempt_defaults(db_session):
    attempt = LoginAttempt(email_hash="a" * 64, ip_address="203.0.113.5")
    db_session.add(attempt)
    db_session.flush()
    db_session.refresh(attempt)

    assert isinstance(attempt.id, uuid.UUID)
    assert attempt.attempted_at.tzinfo is not None
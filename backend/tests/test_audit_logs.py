import uuid

import pytest

from app.modules.operations import audit
from app.modules.operations.audit import AuditAction
from app.modules.operations.models import AuditLog
from tests.ledger_helpers import (
    expect_flush_rejected,
    expect_rejected,
    make_user,
)


def test_audit_log_gets_uuid_and_defaults(db_session):
    user = make_user(db_session)
    entry = AuditLog(user_id=user.id, action="wallet.created")
    db_session.add(entry)
    db_session.flush()
    db_session.refresh(entry)

    assert isinstance(entry.id, uuid.UUID)
    assert entry.created_at.tzinfo is not None
    assert entry.event_metadata == {}


def test_audit_log_allows_an_unknown_user(db_session):
    entry = AuditLog(user_id=None, action="auth.login_failed")
    db_session.add(entry)
    db_session.flush()

    assert entry.user_id is None


def test_audit_log_requires_an_existing_user(db_session):
    expect_rejected(
        db_session, AuditLog(user_id=uuid.uuid4(), action="wallet.created")
    )


def test_audit_log_action_cannot_be_blank(db_session):
    user = make_user(db_session)

    expect_rejected(db_session, AuditLog(user_id=user.id, action="   "))


def test_audit_log_metadata_must_be_an_object(db_session):
    user = make_user(db_session)

    expect_rejected(
        db_session,
        AuditLog(user_id=user.id, action="x.y", event_metadata=["bukan", "objek"]),
    )


def test_audit_log_cannot_be_updated(db_session):
    user = make_user(db_session)
    entry = audit.record(
        db_session, user_id=user.id, action=AuditAction.WALLET_CREATED
    )

    entry.action = "wallet.diubah"

    expect_flush_rejected(db_session)


def test_audit_log_cannot_be_deleted(db_session):
    user = make_user(db_session)
    entry = audit.record(
        db_session, user_id=user.id, action=AuditAction.WALLET_CREATED
    )

    db_session.delete(entry)

    expect_flush_rejected(db_session)


def test_record_stores_every_field(db_session):
    user = make_user(db_session)
    resource_id = uuid.uuid4()

    entry = audit.record(
        db_session,
        user_id=user.id,
        action=AuditAction.WALLET_UPDATED,
        resource_type="wallet",
        resource_id=resource_id,
        metadata={"fields": ["name"]},
        ip_address="203.0.113.7",
    )

    assert entry.user_id == user.id
    assert entry.action == "wallet.updated"
    assert entry.resource_type == "wallet"
    assert entry.resource_id == resource_id
    assert entry.event_metadata == {"fields": ["name"]}
    assert entry.ip_address == "203.0.113.7"


@pytest.mark.parametrize("key", ["password", "TOKEN", "amount"])
def test_record_refuses_sensitive_metadata_keys(db_session, key):
    user = make_user(db_session)

    with pytest.raises(ValueError):
        audit.record(
            db_session,
            user_id=user.id,
            action=AuditAction.WALLET_CREATED,
            metadata={key: "apa saja"},
        )
import json
import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.modules.financial_core import service as ledger_service
from app.modules.identity import rate_limit
from app.modules.identity.models import User, UserSession
from app.modules.operations.models import AuditLog
from app.modules.wallet import service as wallet_service
from app.modules.wallet.enums import WalletType
from tests.api_helpers import (
    TRANSACTIONS,
    WALLETS,
    fund,
    new_draft,
    new_key,
    new_wallet,
    post_ok,
    post_tx,
    reverse_ok,
    reverse_tx,
    spend,
)
from tests.helpers import PASSWORD, csrf_headers, sign_up_and_login
from tests.ledger_helpers import make_user

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
SESSIONS = "/api/v1/auth/sessions"
ME = "/api/v1/auth/me"
EMAIL = "budi@example.com"
IP = "testclient"


@pytest.fixture
def me(client):
    sign_up_and_login(client, EMAIL)
    return client


def rows(db, action):
    return (
        db.execute(select(AuditLog).where(AuditLog.action == action))
        .scalars()
        .all()
    )


def user_id_of(db, email=EMAIL):
    return db.execute(select(User.id).where(User.email == email)).scalar_one()


# ---------- autentikasi ----------


def test_registration_is_audited(client, db_session):
    client.post(
        REGISTER,
        json={"email": EMAIL, "password": PASSWORD, "full_name": "Budi"},
    )

    [row] = rows(db_session, "auth.registered")
    assert row.user_id == user_id_of(db_session)
    assert row.resource_type == "user"
    assert row.resource_id == row.user_id
    assert row.ip_address == IP


def test_successful_login_is_audited(me, db_session):
    [row] = rows(db_session, "auth.login_succeeded")

    session_id = db_session.execute(select(UserSession.id)).scalar_one()
    assert row.user_id == user_id_of(db_session)
    assert row.resource_type == "session"
    assert row.resource_id == session_id


def test_failed_login_of_a_known_user_is_audited_without_the_email(
    client, db_session
):
    client.post(
        REGISTER,
        json={"email": EMAIL, "password": PASSWORD, "full_name": "Budi"},
    )

    response = client.post(
        LOGIN, json={"email": EMAIL, "password": "salah-salah-salah"}
    )

    assert response.status_code == 401
    [row] = rows(db_session, "auth.login_failed")
    assert row.user_id == user_id_of(db_session)
    assert row.event_metadata == {
        "email_fingerprint": rate_limit.email_fingerprint(EMAIL)
    }
    assert EMAIL not in json.dumps(row.event_metadata)


def test_failed_login_of_an_unknown_email_has_no_user(client, db_session):
    client.post(
        LOGIN,
        json={"email": "tidak-ada@example.com", "password": "salah-salah-1"},
    )

    [row] = rows(db_session, "auth.login_failed")
    assert row.user_id is None
    assert "tidak-ada@example.com" not in json.dumps(row.event_metadata)


def test_throttled_attempts_are_not_audited(client, db_session):
    limit = settings.login_max_failures_per_account_ip
    for _ in range(limit + 3):
        client.post(
            LOGIN, json={"email": EMAIL, "password": "salah-salah-salah"}
        )

    assert len(rows(db_session, "auth.login_failed")) == limit


def test_logout_is_audited(me, db_session):
    me.post(LOGOUT, headers=csrf_headers(me))

    [row] = rows(db_session, "auth.logout")
    assert row.user_id == user_id_of(db_session)
    assert row.resource_type == "session"


def test_logout_without_a_session_writes_nothing(client, db_session):
    client.post(LOGOUT)

    assert rows(db_session, "auth.logout") == []


def test_session_revocation_is_audited(me, db_session):
    session_id = me.get(SESSIONS).json()[0]["id"]

    response = me.delete(
        f"{SESSIONS}/{session_id}", headers=csrf_headers(me)
    )

    assert response.status_code == 204
    [row] = rows(db_session, "auth.session_revoked")
    assert row.resource_id == uuid.UUID(session_id)


def test_timezone_change_is_audited(me, db_session):
    me.patch(ME, json={"timezone": "Asia/Jakarta"}, headers=csrf_headers(me))

    [row] = rows(db_session, "user.timezone_changed")
    assert row.event_metadata == {"timezone": "Asia/Jakarta"}


# ---------- wallet ----------


def test_wallet_creation_is_audited(me, db_session):
    wallet = new_wallet(me)

    [row] = rows(db_session, "wallet.created")
    assert row.resource_type == "wallet"
    assert row.resource_id == uuid.UUID(wallet["id"])
    assert row.event_metadata == {"wallet_type": "BANK"}
    assert row.ip_address == IP


def test_wallet_update_is_audited_with_field_names_only(me, db_session):
    wallet = new_wallet(me)

    me.patch(
        f"{WALLETS}/{wallet['id']}",
        json={"name": "Nama Baru"},
        headers=csrf_headers(me),
    )

    [row] = rows(db_session, "wallet.updated")
    assert row.event_metadata == {"fields": ["name"]}
    assert "Nama Baru" not in json.dumps(row.event_metadata)


def test_wallet_archiving_is_audited(me, db_session):
    wallet = new_wallet(me)

    me.post(f"{WALLETS}/{wallet['id']}/archive", headers=csrf_headers(me))

    [row] = rows(db_session, "wallet.archived")
    assert row.resource_id == uuid.UUID(wallet["id"])


def test_failed_wallet_creation_writes_no_audit(db_session, monkeypatch):
    user = make_user(db_session)
    db_session.commit()

    def boom(*args, **kwargs):
        raise RuntimeError("gagal membuat akun")

    monkeypatch.setattr(ledger_service, "create_wallet_asset_account", boom)

    with pytest.raises(RuntimeError):
        wallet_service.create_wallet(
            db_session,
            user_id=user.id,
            name="BCA",
            wallet_type=WalletType.BANK,
        )

    assert rows(db_session, "wallet.created") == []


# ---------- posting dan reversal ----------


def test_posting_is_audited_once_even_when_replayed(me, db_session):
    wallet = new_wallet(me)
    draft = new_draft(me, wallet["id"], "INCOME", 100_000)
    key = new_key()

    post_ok(me, draft["id"], key)
    post_ok(me, draft["id"], key)

    [row] = rows(db_session, "transaction.posted")
    assert row.resource_type == "transaction"
    assert row.resource_id == uuid.UUID(draft["id"])
    assert row.event_metadata == {"transaction_type": "INCOME"}


def test_rejected_posting_writes_no_audit(me, db_session):
    wallet = new_wallet(me)
    draft = new_draft(me, wallet["id"], "EXPENSE", 50_000)

    response = post_tx(me, draft["id"])

    assert response.status_code == 409
    assert rows(db_session, "transaction.posted") == []


def test_reversal_is_audited_once_even_when_replayed(me, db_session):
    wallet = new_wallet(me)
    income = fund(me, wallet["id"], 100_000)
    key = new_key()

    first = reverse_ok(me, income["id"], key)
    reverse_ok(me, income["id"], key)

    reversal_rows = rows(db_session, "transaction.reversed")
    [row] = reversal_rows
    assert row.resource_id == uuid.UUID(income["id"])
    assert row.event_metadata == {"reversal_id": first["reversal"]["id"]}


def test_rejected_reversal_writes_no_audit(me, db_session):
    wallet = new_wallet(me)
    income = fund(me, wallet["id"], 100_000)
    spend(me, wallet["id"], 80_000)

    response = reverse_tx(me, income["id"])

    assert response.status_code == 409
    assert rows(db_session, "transaction.reversed") == []


# ---------- kebocoran data ----------


def test_audit_never_contains_credentials_or_amounts(me, db_session):
    wallet = new_wallet(me)
    fund(me, wallet["id"], 123_456)
    token = me.cookies.get(settings.session_cookie_name)

    dump = json.dumps(
        [
            {
                "metadata": row.event_metadata,
                "ip": row.ip_address,
                "action": row.action,
            }
            for row in db_session.execute(select(AuditLog)).scalars()
        ]
    )

    assert PASSWORD not in dump
    assert token not in dump
    assert "123456" not in dump
    assert TRANSACTIONS  # impor dipakai agar tes mudah dilacak
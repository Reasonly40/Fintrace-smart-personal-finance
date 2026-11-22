import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.modules.financial_core.models import LedgerAccount
from app.modules.identity.models import User
from app.modules.wallet.models import Wallet


def make_user(db, email="a@example.com"):
    user = User(email=email, password_hash="hash", full_name="Nama")
    db.add(user)
    db.flush()
    return user


def make_wallet(db, user, name="Bank", **extra):
    wallet = Wallet(user_id=user.id, name=name, wallet_type="BANK", **extra)
    db.add(wallet)
    db.flush()
    return wallet


def make_account(user_id, **overrides):
    values = {
        "user_id": user_id,
        "wallet_id": None,
        "account_code": "INCOME_CONTROL",
        "account_name": "Income Control",
        "account_type": "INCOME",
        "normal_side": "CREDIT",
        "currency": "IDR",
        "is_system": True,
    }
    values.update(overrides)
    return LedgerAccount(**values)


def asset_account(wallet, **overrides):
    user_id = overrides.pop("user_id", wallet.user_id)
    values = {
        "wallet_id": wallet.id,
        "account_code": f"WALLET:{wallet.id}",
        "account_name": wallet.name,
        "account_type": "ASSET",
        "normal_side": "DEBIT",
        "is_system": False,
    }
    values.update(overrides)
    return make_account(user_id, **values)


def expect_rejected(db, obj):
    """Objek harus ditolak database saat flush."""
    db.add(obj)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# ---------- Wallet ----------


def test_wallet_gets_uuid_and_defaults(db_session):
    wallet = make_wallet(db_session, make_user(db_session))
    db_session.refresh(wallet)

    assert isinstance(wallet.id, uuid.UUID)
    assert wallet.currency == "IDR"
    assert wallet.is_active is True
    assert wallet.archived_at is None
    assert wallet.created_at.tzinfo is not None


def test_wallet_name_cannot_be_blank(db_session):
    user = make_user(db_session)
    expect_rejected(
        db_session, Wallet(user_id=user.id, name="   ", wallet_type="BANK")
    )


def test_wallet_type_must_be_known(db_session):
    user = make_user(db_session)
    expect_rejected(
        db_session, Wallet(user_id=user.id, name="Dompet", wallet_type="CRYPTO")
    )


def test_wallet_currency_must_be_idr(db_session):
    user = make_user(db_session)
    expect_rejected(
        db_session,
        Wallet(user_id=user.id, name="Bank", wallet_type="BANK", currency="USD"),
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"is_active": False},
        {"is_active": True, "archived_at": datetime.now(UTC)},
    ],
)
def test_wallet_archive_state_must_be_consistent(db_session, extra):
    user = make_user(db_session)
    expect_rejected(
        db_session,
        Wallet(user_id=user.id, name="Bank", wallet_type="BANK", **extra),
    )


def test_wallet_can_be_archived_consistently(db_session):
    wallet = make_wallet(
        db_session,
        make_user(db_session),
        is_active=False,
        archived_at=datetime.now(UTC),
    )
    assert wallet.is_active is False


def test_wallet_requires_existing_user(db_session):
    expect_rejected(
        db_session,
        Wallet(user_id=uuid.uuid4(), name="Bank", wallet_type="BANK"),
    )


# ---------- LedgerAccount ----------


def test_account_cannot_point_to_another_users_wallet(db_session):
    owner = make_user(db_session, "owner@example.com")
    other = make_user(db_session, "other@example.com")
    wallet = make_wallet(db_session, owner)

    expect_rejected(db_session, asset_account(wallet, user_id=other.id))


def test_wallet_can_have_only_one_asset_account(db_session):
    wallet = make_wallet(db_session, make_user(db_session))
    db_session.add(asset_account(wallet))
    db_session.flush()

    expect_rejected(
        db_session, asset_account(wallet, account_code="WALLET:duplikat")
    )


def test_wallet_account_must_be_asset(db_session):
    wallet = make_wallet(db_session, make_user(db_session))
    expect_rejected(
        db_session,
        asset_account(
            wallet,
            account_type="EXPENSE",
            normal_side="DEBIT",
            is_system=True,
        ),
    )


def test_asset_account_requires_a_wallet(db_session):
    user = make_user(db_session)
    expect_rejected(
        db_session,
        make_account(
            user.id,
            account_code="LIAR_ASSET",
            account_type="ASSET",
            normal_side="DEBIT",
            is_system=False,
        ),
    )


def test_normal_side_must_match_account_type(db_session):
    user = make_user(db_session)
    expect_rejected(db_session, make_account(user.id, normal_side="DEBIT"))


def test_account_type_must_be_known(db_session):
    user = make_user(db_session)
    expect_rejected(db_session, make_account(user.id, account_type="LIABILITY"))


def test_account_code_is_unique_per_user(db_session):
    user = make_user(db_session)
    db_session.add(make_account(user.id))
    db_session.flush()

    expect_rejected(db_session, make_account(user.id))


def test_same_account_code_is_allowed_for_different_users(db_session):
    first = make_user(db_session, "satu@example.com")
    second = make_user(db_session, "dua@example.com")

    db_session.add_all([make_account(first.id), make_account(second.id)])
    db_session.flush()


# ---------- Invariant lintas tabel ----------


def test_wallet_without_asset_account_fails_at_commit_time(db_session):
    make_wallet(db_session, make_user(db_session))

    with pytest.raises(IntegrityError):
        db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    db_session.rollback()


def test_wallet_with_asset_account_passes_the_check(db_session):
    wallet = make_wallet(db_session, make_user(db_session))
    db_session.add(asset_account(wallet))
    db_session.flush()

    db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_wallet_with_accounts_cannot_be_deleted(db_session):
    wallet = make_wallet(db_session, make_user(db_session))
    db_session.add(asset_account(wallet))
    db_session.flush()

    db_session.delete(wallet)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
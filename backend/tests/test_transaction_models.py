import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.modules.financial_core.models import LedgerEntry
from tests.ledger_helpers import (
    add_entry,
    asset_account,
    build_transaction,
    expect_rejected,
    make_transaction,
    make_user,
    make_wallet,
)

BAD_SHAPES = [
    {"transaction_type": "INCOME"},
    {"transaction_type": "INCOME", "wallet_id": "W1", "from_wallet_id": "W2"},
    {"transaction_type": "EXPENSE", "wallet_id": "W1", "to_wallet_id": "W2"},
    {"transaction_type": "OPENING_BALANCE"},
    {
        "transaction_type": "TRANSFER",
        "wallet_id": "W1",
        "from_wallet_id": "W1",
        "to_wallet_id": "W2",
    },
    {"transaction_type": "TRANSFER", "from_wallet_id": "W1"},
    {"transaction_type": "TRANSFER", "to_wallet_id": "W1"},
]

GOOD_SHAPES = [
    {"transaction_type": "INCOME", "wallet_id": "W1"},
    {"transaction_type": "EXPENSE", "wallet_id": "W1"},
    {"transaction_type": "OPENING_BALANCE", "wallet_id": "W1"},
    {
        "transaction_type": "TRANSFER",
        "from_wallet_id": "W1",
        "to_wallet_id": "W2",
    },
]

FOREIGN_WALLET_SHAPES = [
    {"transaction_type": "INCOME", "wallet_id": "THEIRS"},
    {
        "transaction_type": "TRANSFER",
        "from_wallet_id": "MINE",
        "to_wallet_id": "THEIRS",
    },
    {
        "transaction_type": "TRANSFER",
        "from_wallet_id": "THEIRS",
        "to_wallet_id": "MINE",
    },
]


def fill(shape, **ids):
    """Ganti penanda ('W1', 'MINE', ...) dengan UUID wallet sungguhan."""
    return {key: ids.get(value, value) for key, value in shape.items()}


def two_wallets(db):
    user = make_user(db)
    return user, make_wallet(db, user, "Satu"), make_wallet(db, user, "Dua")


# ---------- transactions: kolom dan nilai ----------


def test_transaction_gets_uuid_and_defaults(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)

    tx = make_transaction(db_session, user.id, wallet_id=wallet.id)
    db_session.refresh(tx)

    assert isinstance(tx.id, uuid.UUID)
    assert tx.status == "DRAFT"
    assert tx.currency == "IDR"
    assert tx.posted_at is None
    assert tx.reversal_of_id is None
    assert tx.amount == Decimal(100_000)
    assert tx.created_at.tzinfo is not None


@pytest.mark.parametrize("amount", [0, -1000])
def test_transaction_amount_must_be_positive(db_session, amount):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)

    expect_rejected(
        db_session,
        build_transaction(user.id, wallet_id=wallet.id, amount=Decimal(amount)),
    )


def test_transaction_currency_must_be_idr(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)

    expect_rejected(
        db_session,
        build_transaction(user.id, wallet_id=wallet.id, currency="USD"),
    )


def test_transaction_type_must_be_known(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)

    expect_rejected(
        db_session,
        build_transaction(
            user.id, wallet_id=wallet.id, transaction_type="ADJUSTMENT"
        ),
    )


def test_transaction_status_must_be_known(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)

    expect_rejected(
        db_session,
        build_transaction(user.id, wallet_id=wallet.id, status="PENDING"),
    )


# ---------- transactions: struktur per tipe ----------


@pytest.mark.parametrize("shape", BAD_SHAPES)
def test_wrong_wallet_structure_is_rejected(db_session, shape):
    user, w1, w2 = two_wallets(db_session)

    expect_rejected(
        db_session, build_transaction(user.id, **fill(shape, W1=w1.id, W2=w2.id))
    )


@pytest.mark.parametrize("shape", GOOD_SHAPES)
def test_valid_wallet_structure_is_accepted(db_session, shape):
    user, w1, w2 = two_wallets(db_session)

    make_transaction(db_session, user.id, **fill(shape, W1=w1.id, W2=w2.id))


def test_transfer_to_the_same_wallet_is_rejected(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)

    expect_rejected(
        db_session,
        build_transaction(
            user.id,
            transaction_type="TRANSFER",
            from_wallet_id=wallet.id,
            to_wallet_id=wallet.id,
        ),
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"status": "DRAFT", "posted_at": datetime.now(UTC)},
        {"status": "POSTED", "posted_at": None},
    ],
)
def test_posted_at_must_match_status(db_session, extra):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)

    expect_rejected(
        db_session, build_transaction(user.id, wallet_id=wallet.id, **extra)
    )


@pytest.mark.parametrize("shape", FOREIGN_WALLET_SHAPES)
def test_transaction_cannot_use_another_users_wallet(db_session, shape):
    me = make_user(db_session, "saya@example.com")
    other = make_user(db_session, "lain@example.com")
    mine = make_wallet(db_session, me, "Milik Saya")
    theirs = make_wallet(db_session, other, "Milik Lain")

    values = fill(shape, MINE=mine.id, THEIRS=theirs.id)

    expect_rejected(db_session, build_transaction(me.id, **values))


# ---------- opening balance ----------


def test_wallet_can_have_only_one_active_opening_balance(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    make_transaction(
        db_session,
        user.id,
        transaction_type="OPENING_BALANCE",
        wallet_id=wallet.id,
    )

    expect_rejected(
        db_session,
        build_transaction(
            user.id, transaction_type="OPENING_BALANCE", wallet_id=wallet.id
        ),
    )


def test_opening_balance_is_allowed_for_different_wallets(db_session):
    user, w1, w2 = two_wallets(db_session)

    for wallet in (w1, w2):
        make_transaction(
            db_session,
            user.id,
            transaction_type="OPENING_BALANCE",
            wallet_id=wallet.id,
        )


def test_opening_balance_can_be_redone_after_reversal(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    make_transaction(
        db_session,
        user.id,
        transaction_type="OPENING_BALANCE",
        wallet_id=wallet.id,
        status="REVERSED",
    )

    make_transaction(
        db_session,
        user.id,
        transaction_type="OPENING_BALANCE",
        wallet_id=wallet.id,
    )


# ---------- reversal ----------


def posted_original(db, user, wallet):
    return make_transaction(
        db, user.id, wallet_id=wallet.id, status="POSTED"
    )


def test_reversal_requires_a_link_to_the_original(db_session):
    user = make_user(db_session)

    expect_rejected(
        db_session,
        build_transaction(user.id, transaction_type="REVERSAL", status="POSTED"),
    )


def test_normal_transaction_cannot_have_a_reversal_link(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    original = posted_original(db_session, user, wallet)

    expect_rejected(
        db_session,
        build_transaction(
            user.id, wallet_id=wallet.id, reversal_of_id=original.id
        ),
    )


def test_reversal_must_be_posted(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    original = posted_original(db_session, user, wallet)

    expect_rejected(
        db_session,
        build_transaction(
            user.id,
            transaction_type="REVERSAL",
            reversal_of_id=original.id,
            amount=original.amount,
        ),
    )


def test_a_transaction_can_be_reversed_only_once(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    original = posted_original(db_session, user, wallet)
    fields = {
        "transaction_type": "REVERSAL",
        "status": "POSTED",
        "reversal_of_id": original.id,
        "amount": original.amount,
    }
    make_transaction(db_session, user.id, **fields)

    expect_rejected(db_session, build_transaction(user.id, **fields))


def test_reversal_cannot_point_to_another_users_transaction(db_session):
    owner = make_user(db_session, "pemilik@example.com")
    intruder = make_user(db_session, "penyusup@example.com")
    wallet = make_wallet(db_session, owner)
    original = posted_original(db_session, owner, wallet)

    expect_rejected(
        db_session,
        build_transaction(
            intruder.id,
            transaction_type="REVERSAL",
            status="POSTED",
            reversal_of_id=original.id,
            amount=original.amount,
        ),
    )


# ---------- ledger_entries ----------


def test_valid_ledger_entry_is_accepted(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    tx = make_transaction(db_session, user.id, wallet_id=wallet.id)

    entry = add_entry(db_session, tx, asset_account(db_session, wallet).id, "DEBIT")

    assert entry.amount == tx.amount


def test_entry_amount_must_be_positive(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    tx = make_transaction(db_session, user.id, wallet_id=wallet.id)
    account = asset_account(db_session, wallet)

    expect_rejected(
        db_session,
        LedgerEntry(
            user_id=user.id,
            transaction_id=tx.id,
            account_id=account.id,
            entry_type="DEBIT",
            amount=Decimal(0),
        ),
    )


def test_entry_type_must_be_known(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    tx = make_transaction(db_session, user.id, wallet_id=wallet.id)
    account = asset_account(db_session, wallet)

    expect_rejected(
        db_session,
        LedgerEntry(
            user_id=user.id,
            transaction_id=tx.id,
            account_id=account.id,
            entry_type="DEBITS",
            amount=Decimal(100_000),
        ),
    )


def test_entry_cannot_use_another_users_account(db_session):
    a = make_user(db_session, "a@example.com")
    b = make_user(db_session, "b@example.com")
    wallet_a = make_wallet(db_session, a)
    wallet_b = make_wallet(db_session, b)
    tx = make_transaction(db_session, a.id, wallet_id=wallet_a.id)
    foreign = asset_account(db_session, wallet_b)

    expect_rejected(
        db_session,
        LedgerEntry(
            user_id=a.id,
            transaction_id=tx.id,
            account_id=foreign.id,
            entry_type="DEBIT",
            amount=Decimal(100_000),
        ),
    )


def test_entry_cannot_use_another_users_transaction(db_session):
    a = make_user(db_session, "a@example.com")
    b = make_user(db_session, "b@example.com")
    wallet_a = make_wallet(db_session, a)
    wallet_b = make_wallet(db_session, b)
    tx_of_a = make_transaction(db_session, a.id, wallet_id=wallet_a.id)
    account_of_b = asset_account(db_session, wallet_b)

    expect_rejected(
        db_session,
        LedgerEntry(
            user_id=b.id,
            transaction_id=tx_of_a.id,
            account_id=account_of_b.id,
            entry_type="DEBIT",
            amount=Decimal(100_000),
        ),
    )
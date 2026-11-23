import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.financial_core import service as ledger_service
from app.modules.financial_core.balance import wallet_balance
from app.modules.financial_core.enums import TransactionType
from app.modules.financial_core.errors import (
    InsufficientBalanceError,
    InvalidAmountError,
    OpeningBalanceNotAllowedError,
    TransactionNotDraftError,
    TransactionNotFoundError,
    UnsupportedTransactionTypeError,
    WalletNotActiveError,
)
from app.modules.financial_core.models import LedgerEntry
from app.modules.operations.errors import IdempotencyKeyReusedError
from app.modules.wallet import service as wallet_service
from app.modules.wallet.errors import WalletNotFoundError
from tests.ledger_helpers import (
    asset_account,
    control_account,
    make_user,
    make_wallet,
    validate_deferred,
)

INCOME = TransactionType.INCOME
EXPENSE = TransactionType.EXPENSE
OPENING = TransactionType.OPENING_BALANCE


def draft(db, user, wallet, kind, amount):
    """Buat DRAFT dan commit, supaya tidak ikut batal bila ada rollback."""
    tx = ledger_service.create_draft(
        db,
        user_id=user.id,
        transaction_type=kind,
        amount=amount,
        wallet_id=wallet.id,
        occurred_at=datetime.now(UTC),
    )
    db.commit()
    return tx


def post(db, user, tx):
    return ledger_service.post_transaction(
        db, user_id=user.id, transaction_id=tx.id
    )


def fund(db, user, wallet, amount):
    """Isi saldo lewat income yang diposting."""
    post(db, user, draft(db, user, wallet, INCOME, amount))
    db.commit()


def balance(db, user, wallet):
    return wallet_balance(db, user_id=user.id, wallet_id=wallet.id)


def entries_of(db, tx):
    return (
        db.execute(
            select(LedgerEntry).where(LedgerEntry.transaction_id == tx.id)
        )
        .scalars()
        .all()
    )


def world(db, email="a@example.com"):
    user = make_user(db, email)
    return user, make_wallet(db, user)


# ---------- create_draft ----------


def test_create_draft_stores_a_draft_without_entries(db_session):
    user, wallet = world(db_session)

    tx = ledger_service.create_draft(
        db_session,
        user_id=user.id,
        transaction_type=EXPENSE,
        amount=25_000,
        wallet_id=wallet.id,
        occurred_at=datetime.now(UTC),
        description="Makan siang",
    )

    assert tx.status == "DRAFT"
    assert tx.amount == Decimal(25_000)
    assert tx.wallet_id == wallet.id
    assert tx.posted_at is None
    assert entries_of(db_session, tx) == []


def test_create_draft_rejects_another_users_wallet(db_session):
    _, wallet = world(db_session, "pemilik@example.com")
    stranger = make_user(db_session, "asing@example.com")

    with pytest.raises(WalletNotFoundError):
        ledger_service.create_draft(
            db_session,
            user_id=stranger.id,
            transaction_type=INCOME,
            amount=1_000,
            wallet_id=wallet.id,
            occurred_at=datetime.now(UTC),
        )


def test_create_draft_rejects_an_archived_wallet(db_session):
    user, wallet = world(db_session)
    wallet_service.archive_wallet(
        db_session, user_id=user.id, wallet_id=wallet.id
    )

    with pytest.raises(WalletNotActiveError):
        ledger_service.create_draft(
            db_session,
            user_id=user.id,
            transaction_type=INCOME,
            amount=1_000,
            wallet_id=wallet.id,
            occurred_at=datetime.now(UTC),
        )


@pytest.mark.parametrize("kind", [TransactionType.REVERSAL])
def test_create_draft_rejects_types_not_yet_supported(db_session, kind):
    user, wallet = world(db_session)

    with pytest.raises(UnsupportedTransactionTypeError):
        ledger_service.create_draft(
            db_session,
            user_id=user.id,
            transaction_type=kind,
            amount=1_000,
            wallet_id=wallet.id,
            occurred_at=datetime.now(UTC),
        )


@pytest.mark.parametrize("amount", [0, -5])
def test_create_draft_rejects_non_positive_amounts(db_session, amount):
    user, wallet = world(db_session)

    with pytest.raises(InvalidAmountError):
        ledger_service.create_draft(
            db_session,
            user_id=user.id,
            transaction_type=INCOME,
            amount=amount,
            wallet_id=wallet.id,
            occurred_at=datetime.now(UTC),
        )


# ---------- post_transaction ----------


def test_posting_income_creates_a_balanced_journal(db_session):
    user, wallet = world(db_session)
    tx = draft(db_session, user, wallet, INCOME, 100_000)

    posted = post(db_session, user, tx)

    assert posted.status == "POSTED"
    assert posted.posted_at is not None
    rows = entries_of(db_session, posted)
    by_type = {row.entry_type: row.account_id for row in rows}
    assert len(rows) == 2
    assert {int(row.amount) for row in rows} == {100_000}
    assert by_type["DEBIT"] == asset_account(db_session, wallet).id
    income = control_account(db_session, user.id, "INCOME_CONTROL")
    assert by_type["CREDIT"] == income.id
    assert balance(db_session, user, wallet) == 100_000
    validate_deferred(db_session)


def test_posting_expense_reduces_the_balance(db_session):
    user, wallet = world(db_session)
    fund(db_session, user, wallet, 100_000)
    tx = draft(db_session, user, wallet, EXPENSE, 30_000)

    posted = post(db_session, user, tx)

    by_type = {row.entry_type: row.account_id for row in entries_of(db_session, posted)}
    expense = control_account(db_session, user.id, "EXPENSE_CONTROL")
    assert by_type["DEBIT"] == expense.id
    assert by_type["CREDIT"] == asset_account(db_session, wallet).id
    assert balance(db_session, user, wallet) == 70_000
    validate_deferred(db_session)


def test_expense_above_the_balance_is_rejected(db_session):
    user, wallet = world(db_session)
    fund(db_session, user, wallet, 10_000)
    tx = draft(db_session, user, wallet, EXPENSE, 20_000)

    with pytest.raises(InsufficientBalanceError):
        post(db_session, user, tx)

    db_session.refresh(tx)
    assert tx.status == "DRAFT"
    assert entries_of(db_session, tx) == []
    assert balance(db_session, user, wallet) == 10_000


def test_expense_equal_to_the_balance_is_allowed(db_session):
    user, wallet = world(db_session)
    fund(db_session, user, wallet, 50_000)

    post(db_session, user, draft(db_session, user, wallet, EXPENSE, 50_000))

    assert balance(db_session, user, wallet) == 0


def test_opening_balance_credits_equity(db_session):
    user, wallet = world(db_session)
    tx = draft(db_session, user, wallet, OPENING, 1_000_000)

    posted = post(db_session, user, tx)

    by_type = {row.entry_type: row.account_id for row in entries_of(db_session, posted)}
    equity = control_account(db_session, user.id, "OPENING_BALANCE_EQUITY")
    assert by_type["CREDIT"] == equity.id
    assert balance(db_session, user, wallet) == 1_000_000
    validate_deferred(db_session)


def test_opening_balance_is_rejected_once_the_wallet_has_activity(db_session):
    user, wallet = world(db_session)
    fund(db_session, user, wallet, 100_000)
    tx = draft(db_session, user, wallet, OPENING, 500_000)

    with pytest.raises(OpeningBalanceNotAllowedError):
        post(db_session, user, tx)

    assert balance(db_session, user, wallet) == 100_000


def test_posting_twice_is_rejected(db_session):
    user, wallet = world(db_session)
    tx = draft(db_session, user, wallet, INCOME, 100_000)
    post(db_session, user, tx)

    with pytest.raises(TransactionNotDraftError):
        post(db_session, user, tx)

    assert len(entries_of(db_session, tx)) == 2


def test_posting_an_unknown_transaction(db_session):
    user, _ = world(db_session)

    with pytest.raises(TransactionNotFoundError):
        ledger_service.post_transaction(
            db_session, user_id=user.id, transaction_id=uuid.uuid4()
        )


def test_posting_another_users_transaction_looks_like_not_found(db_session):
    owner, wallet = world(db_session, "pemilik@example.com")
    stranger = make_user(db_session, "asing@example.com")
    tx = draft(db_session, owner, wallet, INCOME, 100_000)

    with pytest.raises(TransactionNotFoundError):
        post(db_session, stranger, tx)

    db_session.refresh(tx)
    assert tx.status == "DRAFT"


def test_posting_to_a_wallet_archived_after_the_draft(db_session):
    user, wallet = world(db_session)
    tx = draft(db_session, user, wallet, INCOME, 100_000)
    wallet_service.archive_wallet(
        db_session, user_id=user.id, wallet_id=wallet.id
    )

    with pytest.raises(WalletNotActiveError):
        post(db_session, user, tx)

    db_session.refresh(tx)
    assert tx.status == "DRAFT"


# ---------- post_with_idempotency ----------


def command(db, user, tx, key):
    return ledger_service.post_with_idempotency(
        db, user_id=user.id, transaction_id=tx.id, idempotency_key=key
    )


def test_first_call_posts_the_transaction(db_session):
    user, wallet = world(db_session)
    tx = draft(db_session, user, wallet, INCOME, 100_000)

    result = command(db_session, user, tx, "key-1")

    assert result.replayed is False
    assert result.transaction_id == tx.id
    db_session.refresh(tx)
    assert tx.status == "POSTED"
    assert balance(db_session, user, wallet) == 100_000


def test_repeated_call_replays_without_posting_again(db_session):
    user, wallet = world(db_session)
    tx = draft(db_session, user, wallet, INCOME, 100_000)
    command(db_session, user, tx, "key-1")

    again = command(db_session, user, tx, "key-1")

    assert again.replayed is True
    assert again.transaction_id == tx.id
    assert len(entries_of(db_session, tx)) == 2
    assert balance(db_session, user, wallet) == 100_000
    count = db_session.execute(
        select(func.count()).select_from(LedgerEntry)
    ).scalar_one()
    assert count == 2


def test_same_key_for_another_transaction_is_a_conflict(db_session):
    user, wallet = world(db_session)
    first = draft(db_session, user, wallet, INCOME, 100_000)
    second = draft(db_session, user, wallet, INCOME, 50_000)
    command(db_session, user, first, "key-1")

    with pytest.raises(IdempotencyKeyReusedError):
        command(db_session, user, second, "key-1")

    db_session.refresh(second)
    assert second.status == "DRAFT"
    assert balance(db_session, user, wallet) == 100_000


def test_a_failed_posting_does_not_burn_the_key(db_session):
    user, wallet = world(db_session)
    expense = draft(db_session, user, wallet, EXPENSE, 50_000)

    with pytest.raises(InsufficientBalanceError):
        command(db_session, user, expense, "key-1")

    fund(db_session, user, wallet, 100_000)
    retry = command(db_session, user, expense, "key-1")

    assert retry.replayed is False
    assert balance(db_session, user, wallet) == 50_000


def test_users_can_reuse_the_same_key_independently(db_session):
    first, first_wallet = world(db_session, "satu@example.com")
    second, second_wallet = world(db_session, "dua@example.com")
    tx_one = draft(db_session, first, first_wallet, INCOME, 100_000)
    tx_two = draft(db_session, second, second_wallet, INCOME, 200_000)

    one = command(db_session, first, tx_one, "key-1")
    two = command(db_session, second, tx_two, "key-1")

    assert one.replayed is False
    assert two.replayed is False
    assert balance(db_session, first, first_wallet) == 100_000
    assert balance(db_session, second, second_wallet) == 200_000
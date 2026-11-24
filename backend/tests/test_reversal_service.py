import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.modules.financial_core import service as ledger_service
from app.modules.financial_core.balance import wallet_balance
from app.modules.financial_core.enums import TransactionType
from app.modules.financial_core.errors import (
    InsufficientBalanceError,
    ReversalNotAllowedError,
    TransactionAlreadyReversedError,
    TransactionNotFoundError,
    TransactionNotPostedError,
    WalletNotActiveError,
)
from app.modules.financial_core.models import LedgerEntry, Transaction
from app.modules.operations.errors import IdempotencyKeyReusedError
from app.modules.wallet import service as wallet_service
from tests.ledger_helpers import (
    make_user,
    make_wallet,
    validate_deferred,
)

INCOME = TransactionType.INCOME
EXPENSE = TransactionType.EXPENSE
OPENING = TransactionType.OPENING_BALANCE
TRANSFER = TransactionType.TRANSFER


def world(db, email="a@example.com"):
    user = make_user(db, email)
    return user, make_wallet(db, user, "Asal"), make_wallet(db, user, "Tujuan")


def make_draft(db, user, kind, amount, wallet=None, source=None, target=None):
    """Buat draft dan commit, supaya tidak ikut batal bila ada rollback."""
    tx = ledger_service.create_draft(
        db,
        user_id=user.id,
        transaction_type=kind,
        amount=amount,
        wallet_id=wallet.id if wallet else None,
        from_wallet_id=source.id if source else None,
        to_wallet_id=target.id if target else None,
        occurred_at=datetime.now(UTC),
    )
    db.commit()
    return tx


def post_new(db, user, kind, amount, **wallets):
    tx = make_draft(db, user, kind, amount, **wallets)
    ledger_service.post_transaction(db, user_id=user.id, transaction_id=tx.id)
    db.commit()
    return tx


def reverse(db, user, tx, reason="Salah input"):
    return ledger_service.reverse_transaction(
        db, user_id=user.id, transaction_id=tx.id, reason=reason
    )


def reverse_idem(db, user, tx, key, reason="Salah input"):
    return ledger_service.reverse_with_idempotency(
        db,
        user_id=user.id,
        transaction_id=tx.id,
        reason=reason,
        idempotency_key=key,
    )


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


def reversal_count(db):
    return db.execute(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.transaction_type == "REVERSAL")
    ).scalar_one()


# ---------- hasil reversal ----------


def test_reversing_income_neutralises_it_and_keeps_history(db_session):
    user, wallet, _ = world(db_session)
    income = post_new(db_session, user, INCOME, 100_000, wallet=wallet)

    reversal = reverse(db_session, user, income, "Salah catat")

    db_session.refresh(income)
    assert income.status == "REVERSED"
    assert reversal.transaction_type == "REVERSAL"
    assert reversal.status == "POSTED"
    assert reversal.reversal_of_id == income.id
    assert reversal.amount == income.amount
    assert reversal.description == "Salah catat"
    assert reversal.wallet_id is None
    assert reversal.posted_at is not None
    # Histori asli tetap ada, dan jurnal reversal adalah cerminnya
    assert len(entries_of(db_session, income)) == 2
    original = {
        (e.account_id, e.entry_type) for e in entries_of(db_session, income)
    }
    mirrored = {
        (e.account_id, e.entry_type) for e in entries_of(db_session, reversal)
    }
    flipped = {
        (account_id, "CREDIT" if side == "DEBIT" else "DEBIT")
        for account_id, side in original
    }
    assert mirrored == flipped
    assert balance(db_session, user, wallet) == 0
    validate_deferred(db_session)


def test_reversing_an_expense_restores_the_balance(db_session):
    user, wallet, _ = world(db_session)
    post_new(db_session, user, INCOME, 100_000, wallet=wallet)
    expense = post_new(db_session, user, EXPENSE, 30_000, wallet=wallet)
    assert balance(db_session, user, wallet) == 70_000

    reverse(db_session, user, expense)

    assert balance(db_session, user, wallet) == 100_000
    validate_deferred(db_session)


def test_reversing_a_transfer_moves_the_money_back(db_session):
    user, source, target = world(db_session)
    post_new(db_session, user, INCOME, 100_000, wallet=source)
    transfer = post_new(
        db_session, user, TRANSFER, 40_000, source=source, target=target
    )

    reverse(db_session, user, transfer)

    assert balance(db_session, user, source) == 100_000
    assert balance(db_session, user, target) == 0
    validate_deferred(db_session)


def test_opening_balance_can_be_reversed_and_replaced(db_session):
    user, wallet, _ = world(db_session)
    opening = post_new(db_session, user, OPENING, 1_000_000, wallet=wallet)
    reverse(db_session, user, opening, "Salah saldo awal")
    db_session.commit()
    assert balance(db_session, user, wallet) == 0

    replacement = make_draft(db_session, user, OPENING, 500_000, wallet=wallet)
    ledger_service.post_transaction(
        db_session, user_id=user.id, transaction_id=replacement.id
    )

    assert balance(db_session, user, wallet) == 500_000
    validate_deferred(db_session)


# ---------- aturan penolakan ----------


def test_reversing_income_already_spent_is_rejected(db_session):
    user, wallet, _ = world(db_session)
    income = post_new(db_session, user, INCOME, 100_000, wallet=wallet)
    post_new(db_session, user, EXPENSE, 80_000, wallet=wallet)

    with pytest.raises(InsufficientBalanceError):
        reverse(db_session, user, income)

    db_session.refresh(income)
    assert income.status == "POSTED"
    assert reversal_count(db_session) == 0
    assert balance(db_session, user, wallet) == 20_000


def test_reversing_a_transfer_whose_money_was_spent_is_rejected(db_session):
    user, source, target = world(db_session)
    post_new(db_session, user, INCOME, 100_000, wallet=source)
    transfer = post_new(
        db_session, user, TRANSFER, 100_000, source=source, target=target
    )
    post_new(db_session, user, EXPENSE, 50_000, wallet=target)

    with pytest.raises(InsufficientBalanceError):
        reverse(db_session, user, transfer)

    assert reversal_count(db_session) == 0
    assert balance(db_session, user, target) == 50_000


def test_draft_cannot_be_reversed(db_session):
    user, wallet, _ = world(db_session)
    draft = make_draft(db_session, user, INCOME, 100_000, wallet=wallet)

    with pytest.raises(TransactionNotPostedError):
        reverse(db_session, user, draft)


def test_a_transaction_can_be_reversed_only_once(db_session):
    user, wallet, _ = world(db_session)
    income = post_new(db_session, user, INCOME, 100_000, wallet=wallet)
    reverse(db_session, user, income)
    db_session.commit()

    with pytest.raises(TransactionAlreadyReversedError):
        reverse(db_session, user, income)

    assert reversal_count(db_session) == 1


def test_a_reversal_cannot_be_reversed(db_session):
    user, wallet, _ = world(db_session)
    income = post_new(db_session, user, INCOME, 100_000, wallet=wallet)
    reversal = reverse(db_session, user, income)
    db_session.commit()

    with pytest.raises(ReversalNotAllowedError):
        reverse(db_session, user, reversal)


def test_unknown_transaction_is_not_found(db_session):
    user, _, _ = world(db_session)

    with pytest.raises(TransactionNotFoundError):
        ledger_service.reverse_transaction(
            db_session,
            user_id=user.id,
            transaction_id=uuid.uuid4(),
            reason="apa saja",
        )


def test_foreign_transaction_looks_like_not_found(db_session):
    owner, wallet, _ = world(db_session, "pemilik@example.com")
    stranger = make_user(db_session, "asing@example.com")
    income = post_new(db_session, owner, INCOME, 100_000, wallet=wallet)

    with pytest.raises(TransactionNotFoundError):
        reverse(db_session, stranger, income)

    db_session.refresh(income)
    assert income.status == "POSTED"


def test_reversal_needs_the_wallet_to_be_active(db_session):
    user, wallet, _ = world(db_session)
    post_new(db_session, user, INCOME, 100_000, wallet=wallet)
    expense = post_new(db_session, user, EXPENSE, 100_000, wallet=wallet)
    wallet_service.archive_wallet(
        db_session, user_id=user.id, wallet_id=wallet.id
    )

    with pytest.raises(WalletNotActiveError):
        reverse(db_session, user, expense)


# ---------- idempotency ----------


def test_reversal_is_idempotent(db_session):
    user, wallet, _ = world(db_session)
    income = post_new(db_session, user, INCOME, 100_000, wallet=wallet)

    first = reverse_idem(db_session, user, income, "rev-key-001")
    again = reverse_idem(db_session, user, income, "rev-key-001")

    assert first.replayed is False
    assert again.replayed is True
    assert again.reversal_id == first.reversal_id
    assert reversal_count(db_session) == 1
    assert balance(db_session, user, wallet) == 0


def test_same_key_with_a_different_reason_is_a_conflict(db_session):
    user, wallet, _ = world(db_session)
    income = post_new(db_session, user, INCOME, 100_000, wallet=wallet)
    reverse_idem(db_session, user, income, "rev-key-001", "Alasan satu")

    with pytest.raises(IdempotencyKeyReusedError):
        reverse_idem(db_session, user, income, "rev-key-001", "Alasan dua")


def test_failed_reversal_does_not_burn_the_key(db_session):
    user, wallet, _ = world(db_session)
    income = post_new(db_session, user, INCOME, 100_000, wallet=wallet)
    expense = post_new(db_session, user, EXPENSE, 80_000, wallet=wallet)

    with pytest.raises(InsufficientBalanceError):
        reverse_idem(db_session, user, income, "rev-key-001")

    reverse(db_session, user, expense)  # membebaskan saldo
    db_session.commit()
    retry = reverse_idem(db_session, user, income, "rev-key-001")

    assert retry.replayed is False
    assert balance(db_session, user, wallet) == 0


# ---------- penelusuran ----------


def test_reversal_can_be_traced_from_the_original(db_session):
    user, wallet, _ = world(db_session)
    income = post_new(db_session, user, INCOME, 100_000, wallet=wallet)
    assert (
        ledger_service.get_reversal_id(
            db_session, user_id=user.id, transaction_id=income.id
        )
        is None
    )

    reversal = reverse(db_session, user, income)

    found = ledger_service.get_reversal_id(
        db_session, user_id=user.id, transaction_id=income.id
    )
    assert found == reversal.id


def test_reversal_keeps_the_period_of_the_original(db_session):
    user, wallet, _ = world(db_session)
    income = post_new(db_session, user, INCOME, 100_000, wallet=wallet)
    original_time = income.occurred_at
    original_posted_at = income.posted_at

    reversal = reverse(db_session, user, income)

    assert reversal.occurred_at == original_time
    assert reversal.posted_at is not None
    assert reversal.posted_at >= original_posted_at
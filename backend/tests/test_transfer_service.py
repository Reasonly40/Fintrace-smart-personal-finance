from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.modules.financial_core import service as ledger_service
from app.modules.financial_core.balance import wallet_balance
from app.modules.financial_core.enums import TransactionType
from app.modules.financial_core.errors import (
    InsufficientBalanceError,
    InvalidTransactionShapeError,
    SameWalletTransferError,
    WalletNotActiveError,
)
from app.modules.financial_core.models import LedgerAccount, LedgerEntry
from app.modules.wallet import service as wallet_service
from app.modules.wallet.errors import WalletNotFoundError
from tests.ledger_helpers import (
    asset_account,
    make_user,
    make_wallet,
    validate_deferred,
)

TRANSFER = TransactionType.TRANSFER
INCOME = TransactionType.INCOME


def two_wallets(db, email="a@example.com"):
    user = make_user(db, email)
    return user, make_wallet(db, user, "Asal"), make_wallet(db, user, "Tujuan")


def transfer_draft(db, user, source, destination, amount):
    """Buat draft transfer dan commit, supaya tidak ikut batal bila
    ada rollback."""
    tx = ledger_service.create_draft(
        db,
        user_id=user.id,
        transaction_type=TRANSFER,
        amount=amount,
        from_wallet_id=source.id,
        to_wallet_id=destination.id,
        occurred_at=datetime.now(UTC),
    )
    db.commit()
    return tx


def post(db, user, tx):
    return ledger_service.post_transaction(
        db, user_id=user.id, transaction_id=tx.id
    )


def fund(db, user, wallet, amount):
    income = ledger_service.create_draft(
        db,
        user_id=user.id,
        transaction_type=INCOME,
        amount=amount,
        wallet_id=wallet.id,
        occurred_at=datetime.now(UTC),
    )
    db.commit()
    post(db, user, income)
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


# ---------- create_draft ----------


def test_create_transfer_draft_stores_both_wallets(db_session):
    user, source, destination = two_wallets(db_session)

    tx = ledger_service.create_draft(
        db_session,
        user_id=user.id,
        transaction_type=TRANSFER,
        amount=40_000,
        from_wallet_id=source.id,
        to_wallet_id=destination.id,
        occurred_at=datetime.now(UTC),
    )

    assert tx.status == "DRAFT"
    assert tx.wallet_id is None
    assert tx.from_wallet_id == source.id
    assert tx.to_wallet_id == destination.id
    assert entries_of(db_session, tx) == []


def test_transfer_to_the_same_wallet_is_rejected(db_session):
    user, source, _ = two_wallets(db_session)

    with pytest.raises(SameWalletTransferError):
        ledger_service.create_draft(
            db_session,
            user_id=user.id,
            transaction_type=TRANSFER,
            amount=1_000,
            from_wallet_id=source.id,
            to_wallet_id=source.id,
            occurred_at=datetime.now(UTC),
        )


def test_transfer_with_a_wallet_id_is_rejected(db_session):
    user, source, destination = two_wallets(db_session)

    with pytest.raises(InvalidTransactionShapeError):
        ledger_service.create_draft(
            db_session,
            user_id=user.id,
            transaction_type=TRANSFER,
            amount=1_000,
            wallet_id=source.id,
            from_wallet_id=source.id,
            to_wallet_id=destination.id,
            occurred_at=datetime.now(UTC),
        )


def test_transfer_without_a_destination_is_rejected(db_session):
    user, source, _ = two_wallets(db_session)

    with pytest.raises(InvalidTransactionShapeError):
        ledger_service.create_draft(
            db_session,
            user_id=user.id,
            transaction_type=TRANSFER,
            amount=1_000,
            from_wallet_id=source.id,
            occurred_at=datetime.now(UTC),
        )


def test_income_with_transfer_wallets_is_rejected(db_session):
    user, source, destination = two_wallets(db_session)

    with pytest.raises(InvalidTransactionShapeError):
        ledger_service.create_draft(
            db_session,
            user_id=user.id,
            transaction_type=INCOME,
            amount=1_000,
            wallet_id=source.id,
            from_wallet_id=destination.id,
            occurred_at=datetime.now(UTC),
        )


@pytest.mark.parametrize("foreign_side", ["source", "destination"])
def test_transfer_rejects_a_foreign_wallet(db_session, foreign_side):
    user, mine_one, mine_two = two_wallets(db_session)
    stranger = make_user(db_session, "asing@example.com")
    theirs = make_wallet(db_session, stranger, "Milik Asing")
    source = theirs if foreign_side == "source" else mine_one
    destination = theirs if foreign_side == "destination" else mine_two

    with pytest.raises(WalletNotFoundError):
        ledger_service.create_draft(
            db_session,
            user_id=user.id,
            transaction_type=TRANSFER,
            amount=1_000,
            from_wallet_id=source.id,
            to_wallet_id=destination.id,
            occurred_at=datetime.now(UTC),
        )


@pytest.mark.parametrize("archived_side", ["source", "destination"])
def test_transfer_rejects_an_archived_wallet(db_session, archived_side):
    user, source, destination = two_wallets(db_session)
    target = source if archived_side == "source" else destination
    wallet_service.archive_wallet(
        db_session, user_id=user.id, wallet_id=target.id
    )

    with pytest.raises(WalletNotActiveError):
        ledger_service.create_draft(
            db_session,
            user_id=user.id,
            transaction_type=TRANSFER,
            amount=1_000,
            from_wallet_id=source.id,
            to_wallet_id=destination.id,
            occurred_at=datetime.now(UTC),
        )


# ---------- post_transaction ----------


def test_posting_a_transfer_moves_the_balance(db_session):
    user, source, destination = two_wallets(db_session)
    fund(db_session, user, source, 100_000)

    posted = post(
        db_session,
        user,
        transfer_draft(db_session, user, source, destination, 40_000),
    )

    assert posted.status == "POSTED"
    assert balance(db_session, user, source) == 60_000
    assert balance(db_session, user, destination) == 40_000
    total = balance(db_session, user, source) + balance(
        db_session, user, destination
    )
    assert total == 100_000
    validate_deferred(db_session)


def test_transfer_journal_debits_destination_and_credits_source(db_session):
    user, source, destination = two_wallets(db_session)
    fund(db_session, user, source, 100_000)

    posted = post(
        db_session,
        user,
        transfer_draft(db_session, user, source, destination, 40_000),
    )

    rows = entries_of(db_session, posted)
    by_type = {row.entry_type: row.account_id for row in rows}
    assert by_type["DEBIT"] == asset_account(db_session, destination).id
    assert by_type["CREDIT"] == asset_account(db_session, source).id
    assert {int(row.amount) for row in rows} == {40_000}
    accounts = (
        db_session.execute(
            select(LedgerAccount).where(
                LedgerAccount.id.in_(list(by_type.values()))
            )
        )
        .scalars()
        .all()
    )
    # Hanya akun wallet: transfer bukan income dan bukan expense
    assert {account.account_type for account in accounts} == {"ASSET"}


def test_transfer_above_the_source_balance_is_rejected(db_session):
    user, source, destination = two_wallets(db_session)
    fund(db_session, user, source, 10_000)
    tx = transfer_draft(db_session, user, source, destination, 20_000)

    with pytest.raises(InsufficientBalanceError):
        post(db_session, user, tx)

    db_session.refresh(tx)
    assert tx.status == "DRAFT"
    assert entries_of(db_session, tx) == []
    assert balance(db_session, user, source) == 10_000
    assert balance(db_session, user, destination) == 0


def test_transfer_equal_to_the_source_balance_is_allowed(db_session):
    user, source, destination = two_wallets(db_session)
    fund(db_session, user, source, 50_000)

    post(
        db_session,
        user,
        transfer_draft(db_session, user, source, destination, 50_000),
    )

    assert balance(db_session, user, source) == 0
    assert balance(db_session, user, destination) == 50_000


@pytest.mark.parametrize("archived_side", ["source", "destination"])
def test_posting_with_an_archived_wallet_is_rejected(
    db_session, archived_side
):
    user, source, destination = two_wallets(db_session)
    tx = transfer_draft(db_session, user, source, destination, 1_000)
    target = source if archived_side == "source" else destination
    wallet_service.archive_wallet(
        db_session, user_id=user.id, wallet_id=target.id
    )

    with pytest.raises(WalletNotActiveError):
        post(db_session, user, tx)


def test_transfer_post_is_idempotent(db_session):
    user, source, destination = two_wallets(db_session)
    fund(db_session, user, source, 100_000)
    tx = transfer_draft(db_session, user, source, destination, 40_000)

    first = ledger_service.post_with_idempotency(
        db_session,
        user_id=user.id,
        transaction_id=tx.id,
        idempotency_key="transfer-key-1",
    )
    again = ledger_service.post_with_idempotency(
        db_session,
        user_id=user.id,
        transaction_id=tx.id,
        idempotency_key="transfer-key-1",
    )

    assert first.replayed is False
    assert again.replayed is True
    assert balance(db_session, user, source) == 60_000
    assert balance(db_session, user, destination) == 40_000
    assert len(entries_of(db_session, tx)) == 2


# ---------- penguncian wallet ----------


def test_lock_wallets_rejects_a_foreign_wallet(db_session):
    user, source, _ = two_wallets(db_session)
    stranger = make_user(db_session, "asing@example.com")

    with pytest.raises(WalletNotFoundError):
        ledger_service._lock_wallets(
            db_session, user_id=stranger.id, wallet_ids=[source.id]
        )


def test_lock_wallets_accepts_any_order_and_duplicates(db_session):
    user, source, destination = two_wallets(db_session)

    locked = ledger_service._lock_wallets(
        db_session,
        user_id=user.id,
        wallet_ids=[destination.id, source.id, source.id],
    )

    assert set(locked) == {source.id, destination.id}
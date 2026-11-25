from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.financial_core.models import LedgerEntry, Transaction
from tests.ledger_helpers import (
    add_entry,
    asset_account,
    control_account,
    expect_flush_rejected,
    expect_invalid_at_commit,
    make_transaction,
    make_user,
    make_wallet,
    post_income,
    reverse,
    validate_deferred,
)


def new_world(db):
    user = make_user(db)
    return user, make_wallet(db, user)


def posted_without_entries(db, user, wallet):
    return make_transaction(
        db, user.id, wallet_id=wallet.id, status="POSTED"
    )


# ---------- FIN-003: jurnal seimbang ----------


def test_balanced_journal_passes_the_commit_check(db_session):
    user, wallet = new_world(db_session)

    post_income(db_session, user, wallet)

    validate_deferred(db_session)


def test_unbalanced_journal_is_rejected(db_session):
    user, wallet = new_world(db_session)
    tx = posted_without_entries(db_session, user, wallet)
    add_entry(db_session, tx, asset_account(db_session, wallet).id, "DEBIT")
    income = control_account(db_session, user.id, "INCOME_CONTROL")
    add_entry(db_session, tx, income.id, "CREDIT", amount=Decimal(90_000))

    expect_invalid_at_commit(db_session)


def test_journal_total_must_match_the_header_amount(db_session):
    user, wallet = new_world(db_session)
    tx = posted_without_entries(db_session, user, wallet)  # header 100.000
    add_entry(
        db_session,
        tx,
        asset_account(db_session, wallet).id,
        "DEBIT",
        amount=Decimal(50_000),
    )
    income = control_account(db_session, user.id, "INCOME_CONTROL")
    add_entry(db_session, tx, income.id, "CREDIT", amount=Decimal(50_000))

    expect_invalid_at_commit(db_session)


def test_one_sided_journal_is_rejected(db_session):
    user, wallet = new_world(db_session)
    tx = posted_without_entries(db_session, user, wallet)
    add_entry(db_session, tx, asset_account(db_session, wallet).id, "DEBIT")

    expect_invalid_at_commit(db_session)


# ---------- FIN-002: entries mengikuti status ----------


def test_posted_transaction_without_entries_is_rejected(db_session):
    user, wallet = new_world(db_session)
    posted_without_entries(db_session, user, wallet)

    expect_invalid_at_commit(db_session)


def test_draft_with_entries_is_rejected(db_session):
    user, wallet = new_world(db_session)
    tx = make_transaction(db_session, user.id, wallet_id=wallet.id)
    add_entry(db_session, tx, asset_account(db_session, wallet).id, "DEBIT")
    income = control_account(db_session, user.id, "INCOME_CONTROL")
    add_entry(db_session, tx, income.id, "CREDIT")

    expect_invalid_at_commit(db_session)


def test_draft_without_entries_is_fine(db_session):
    user, wallet = new_world(db_session)
    make_transaction(db_session, user.id, wallet_id=wallet.id)

    validate_deferred(db_session)


# ---------- FIN-009: reversal ----------


def test_reversed_transaction_without_reversal_journal_is_rejected(db_session):
    user, wallet = new_world(db_session)
    original = post_income(db_session, user, wallet)
    original.status = "REVERSED"
    db_session.flush()

    expect_invalid_at_commit(db_session)


def test_reversal_of_a_transaction_not_marked_reversed_is_rejected(db_session):
    user, wallet = new_world(db_session)
    original = post_income(db_session, user, wallet)
    reverse(db_session, original, mark_original=False)

    expect_invalid_at_commit(db_session)


def test_complete_reversal_passes_the_commit_check(db_session):
    user, wallet = new_world(db_session)
    original = post_income(db_session, user, wallet)

    reverse(db_session, original)

    validate_deferred(db_session)


# ---------- FIN-008: transaksi posted immutable ----------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("amount", Decimal(1)),
        ("occurred_at", datetime(2020, 1, 1, tzinfo=UTC)),
    ],
)
def test_posted_transaction_cannot_be_edited(db_session, field, value):
    user, wallet = new_world(db_session)
    tx = post_income(db_session, user, wallet)

    setattr(tx, field, value)

    expect_flush_rejected(db_session)


def test_posted_transaction_cannot_be_deleted(db_session):
    user, wallet = new_world(db_session)
    tx = post_income(db_session, user, wallet)

    db_session.delete(tx)

    expect_flush_rejected(db_session)


def test_draft_can_be_edited_and_deleted(db_session):
    user, wallet = new_world(db_session)
    tx = make_transaction(db_session, user.id, wallet_id=wallet.id)

    tx.description = "boleh diubah"
    db_session.flush()
    tx_id = tx.id
    db_session.delete(tx)
    db_session.flush()

    assert db_session.get(Transaction, tx_id) is None


def test_draft_cannot_jump_straight_to_reversed(db_session):
    user, wallet = new_world(db_session)
    tx = make_transaction(db_session, user.id, wallet_id=wallet.id)

    tx.status = "REVERSED"
    tx.posted_at = datetime.now(UTC)

    expect_flush_rejected(db_session)


def test_draft_can_be_posted_with_its_journal(db_session):
    user, wallet = new_world(db_session)
    tx = make_transaction(db_session, user.id, wallet_id=wallet.id)

    tx.status = "POSTED"
    tx.posted_at = datetime.now(UTC)
    db_session.flush()
    add_entry(db_session, tx, asset_account(db_session, wallet).id, "DEBIT")
    income = control_account(db_session, user.id, "INCOME_CONTROL")
    add_entry(db_session, tx, income.id, "CREDIT")

    validate_deferred(db_session)


def test_reversing_cannot_smuggle_in_other_changes(db_session):
    user, wallet = new_world(db_session)
    tx = post_income(db_session, user, wallet)

    tx.status = "REVERSED"
    tx.amount = Decimal(1)

    expect_flush_rejected(db_session)


def test_reversed_transaction_is_final(db_session):
    user, wallet = new_world(db_session)
    original = post_income(db_session, user, wallet)
    reverse(db_session, original)

    original.status = "POSTED"

    expect_flush_rejected(db_session)


# ---------- ledger_entries immutable ----------


def first_entry(db, tx):
    return db.execute(
        select(LedgerEntry).where(LedgerEntry.transaction_id == tx.id)
    ).scalars().first()


def test_ledger_entry_cannot_be_updated(db_session):
    user, wallet = new_world(db_session)
    entry = first_entry(db_session, post_income(db_session, user, wallet))

    entry.amount = Decimal(1)

    expect_flush_rejected(db_session)


def test_ledger_entry_cannot_be_deleted(db_session):
    user, wallet = new_world(db_session)
    entry = first_entry(db_session, post_income(db_session, user, wallet))

    db_session.delete(entry)

    expect_flush_rejected(db_session)

def test_discarded_draft_does_not_break_the_commit_check(db_session):
    user, wallet = new_world(db_session)
    tx = make_transaction(db_session, user.id, wallet_id=wallet.id)

    db_session.delete(tx)
    db_session.flush()

    validate_deferred(db_session)
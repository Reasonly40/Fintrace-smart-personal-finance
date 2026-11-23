import uuid
from dataclasses import replace

import pytest

from app.modules.financial_core.enums import EntryType
from app.modules.financial_core.errors import (
    JournalError,
    UnsupportedTransactionTypeError,
)
from app.modules.financial_core.journal import (
    JournalAccounts,
    JournalLine,
    assert_balanced,
    build_journal,
)

ACCOUNTS = JournalAccounts(
    income_control_id=uuid.uuid4(),
    expense_control_id=uuid.uuid4(),
    opening_equity_id=uuid.uuid4(),
    wallet_account_id=uuid.uuid4(),
    from_account_id=uuid.uuid4(),
    to_account_id=uuid.uuid4(),
)


def accounts_by_side(lines):
    return {line.entry_type: line.account_id for line in lines}


def test_income_debits_the_wallet_and_credits_income_control():
    sides = accounts_by_side(build_journal("INCOME", 100_000, ACCOUNTS))

    assert sides[EntryType.DEBIT] == ACCOUNTS.wallet_account_id
    assert sides[EntryType.CREDIT] == ACCOUNTS.income_control_id


def test_expense_debits_expense_control_and_credits_the_wallet():
    sides = accounts_by_side(build_journal("EXPENSE", 100_000, ACCOUNTS))

    assert sides[EntryType.DEBIT] == ACCOUNTS.expense_control_id
    assert sides[EntryType.CREDIT] == ACCOUNTS.wallet_account_id


def test_opening_balance_debits_the_wallet_and_credits_equity():
    sides = accounts_by_side(build_journal("OPENING_BALANCE", 100_000, ACCOUNTS))

    assert sides[EntryType.DEBIT] == ACCOUNTS.wallet_account_id
    assert sides[EntryType.CREDIT] == ACCOUNTS.opening_equity_id


def test_transfer_debits_the_destination_and_credits_the_source():
    sides = accounts_by_side(build_journal("TRANSFER", 100_000, ACCOUNTS))

    assert sides[EntryType.DEBIT] == ACCOUNTS.to_account_id
    assert sides[EntryType.CREDIT] == ACCOUNTS.from_account_id


def test_transfer_touches_no_control_account():
    lines = build_journal("TRANSFER", 100_000, ACCOUNTS)

    used = {line.account_id for line in lines}
    assert used == {ACCOUNTS.from_account_id, ACCOUNTS.to_account_id}


@pytest.mark.parametrize("missing", ["from_account_id", "to_account_id"])
def test_transfer_requires_both_wallet_accounts(missing):
    accounts = replace(ACCOUNTS, **{missing: None})

    with pytest.raises(JournalError):
        build_journal("TRANSFER", 100_000, accounts)


def test_transfer_between_the_same_account_is_rejected():
    same = uuid.uuid4()
    accounts = replace(ACCOUNTS, from_account_id=same, to_account_id=same)

    with pytest.raises(JournalError):
        build_journal("TRANSFER", 100_000, accounts)


@pytest.mark.parametrize(
    "kind", ["INCOME", "EXPENSE", "OPENING_BALANCE", "TRANSFER"]
)
def test_every_supported_journal_is_balanced(kind):
    lines = build_journal(kind, 250_000, ACCOUNTS)

    debit = sum(
        line.amount for line in lines if line.entry_type == EntryType.DEBIT
    )
    credit = sum(
        line.amount for line in lines if line.entry_type == EntryType.CREDIT
    )
    assert debit == credit == 250_000
    assert len(lines) == 2


def test_reversal_is_not_supported_yet():
    with pytest.raises(UnsupportedTransactionTypeError):
        build_journal("REVERSAL", 100_000, ACCOUNTS)


def test_non_positive_amount_is_rejected():
    with pytest.raises(JournalError):
        build_journal("INCOME", 0, ACCOUNTS)


def test_unbalanced_lines_are_detected():
    lines = [
        JournalLine(uuid.uuid4(), EntryType.DEBIT, 100),
        JournalLine(uuid.uuid4(), EntryType.CREDIT, 90),
    ]

    with pytest.raises(JournalError):
        assert_balanced(lines, 100)
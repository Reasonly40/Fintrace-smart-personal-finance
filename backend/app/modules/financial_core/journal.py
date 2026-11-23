import uuid
from dataclasses import dataclass

from app.modules.financial_core.enums import EntryType, TransactionType
from app.modules.financial_core.errors import (
    JournalError,
    UnsupportedTransactionTypeError,
)


@dataclass(frozen=True)
class JournalLine:
    account_id: uuid.UUID
    entry_type: EntryType
    amount: int


@dataclass(frozen=True)
class JournalAccounts:
    """Akun-akun yang dibutuhkan untuk menyusun jurnal."""

    wallet_account_id: uuid.UUID
    income_control_id: uuid.UUID
    expense_control_id: uuid.UUID
    opening_equity_id: uuid.UUID


def assert_balanced(lines: list[JournalLine], amount: int) -> None:
    debit = sum(line.amount for line in lines if line.entry_type == EntryType.DEBIT)
    credit = sum(line.amount for line in lines if line.entry_type == EntryType.CREDIT)
    if debit != credit or debit != amount:
        raise JournalError("Jurnal tidak seimbang.")


def build_journal(
    transaction_type: str, amount: int, accounts: JournalAccounts
) -> list[JournalLine]:
    """Susun jurnal sesuai tabel pola jurnal (bagian 7.3 dokumen)."""
    if amount <= 0:
        raise JournalError("Nominal jurnal harus positif.")

    kind = TransactionType(transaction_type)
    if kind == TransactionType.INCOME:
        debit, credit = accounts.wallet_account_id, accounts.income_control_id
    elif kind == TransactionType.EXPENSE:
        debit, credit = accounts.expense_control_id, accounts.wallet_account_id
    elif kind == TransactionType.OPENING_BALANCE:
        debit, credit = accounts.wallet_account_id, accounts.opening_equity_id
    else:
        # TRANSFER (2.6) dan REVERSAL (2.7) menyusul
        raise UnsupportedTransactionTypeError()

    lines = [
        JournalLine(debit, EntryType.DEBIT, amount),
        JournalLine(credit, EntryType.CREDIT, amount),
    ]
    assert_balanced(lines, amount)
    return lines
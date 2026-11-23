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

    income_control_id: uuid.UUID
    expense_control_id: uuid.UUID
    opening_equity_id: uuid.UUID
    # Income, expense, dan opening balance memakai satu akun wallet
    wallet_account_id: uuid.UUID | None = None
    # Transfer memakai akun wallet asal dan tujuan
    from_account_id: uuid.UUID | None = None
    to_account_id: uuid.UUID | None = None


def assert_balanced(lines: list[JournalLine], amount: int) -> None:
    debit = sum(
        line.amount for line in lines if line.entry_type == EntryType.DEBIT
    )
    credit = sum(
        line.amount for line in lines if line.entry_type == EntryType.CREDIT
    )
    if debit != credit or debit != amount:
        raise JournalError("Jurnal tidak seimbang.")


def _need(account_id: uuid.UUID | None) -> uuid.UUID:
    if account_id is None:
        raise JournalError("Akun wallet untuk jurnal ini tidak tersedia.")
    return account_id


def build_journal(
    transaction_type: str, amount: int, accounts: JournalAccounts
) -> list[JournalLine]:
    """Susun jurnal sesuai tabel pola jurnal (bagian 7.3 dokumen)."""
    if amount <= 0:
        raise JournalError("Nominal jurnal harus positif.")

    kind = TransactionType(transaction_type)
    if kind == TransactionType.INCOME:
        debit = _need(accounts.wallet_account_id)
        credit = accounts.income_control_id
    elif kind == TransactionType.EXPENSE:
        debit = accounts.expense_control_id
        credit = _need(accounts.wallet_account_id)
    elif kind == TransactionType.OPENING_BALANCE:
        debit = _need(accounts.wallet_account_id)
        credit = accounts.opening_equity_id
    elif kind == TransactionType.TRANSFER:
        source = _need(accounts.from_account_id)
        destination = _need(accounts.to_account_id)
        if source == destination:
            raise JournalError("Transfer tidak boleh memakai akun yang sama.")
        # Saldo berpindah: debit tujuan, kredit asal
        debit = destination
        credit = source
    else:
        # REVERSAL menyusul di 2.7
        raise UnsupportedTransactionTypeError()

    lines = [
        JournalLine(debit, EntryType.DEBIT, amount),
        JournalLine(credit, EntryType.CREDIT, amount),
    ]
    assert_balanced(lines, amount)
    return lines

def build_reversal_journal(
    original_lines: list[JournalLine], amount: int
) -> list[JournalLine]:
    """Kebalikan seluruh baris jurnal asli (bagian 7.3): akun dan nominal
    sama, sisi debit dan kredit ditukar."""
    if not original_lines:
        raise JournalError("Transaksi asli tidak punya jurnal.")
    flipped = [
        JournalLine(
            account_id=line.account_id,
            entry_type=(
                EntryType.CREDIT
                if line.entry_type == EntryType.DEBIT
                else EntryType.DEBIT
            ),
            amount=line.amount,
        )
        for line in original_lines
    ]
    assert_balanced(flipped, amount)
    return flipped
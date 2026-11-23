from enum import StrEnum


class AccountType(StrEnum):
    ASSET = "ASSET"
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"
    EQUITY = "EQUITY"


class NormalSide(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"

class TransactionType(StrEnum):
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"
    TRANSFER = "TRANSFER"
    OPENING_BALANCE = "OPENING_BALANCE"
    REVERSAL = "REVERSAL"


class TransactionStatus(StrEnum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class EntryType(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"
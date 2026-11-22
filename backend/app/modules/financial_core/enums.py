from enum import StrEnum


class AccountType(StrEnum):
    ASSET = "ASSET"
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"
    EQUITY = "EQUITY"


class NormalSide(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"
from enum import StrEnum


class WalletType(StrEnum):
    BANK = "BANK"
    E_WALLET = "E_WALLET"
    CASH = "CASH"
    OTHER = "OTHER"
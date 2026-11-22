import uuid

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.modules.financial_core.enums import AccountType, NormalSide
from app.modules.financial_core.models import LedgerAccount

CURRENCY = "IDR"

# kode akun -> (nama, tipe, sisi normal); sesuai bagian 7.2 dokumen
SYSTEM_ACCOUNTS: dict[str, tuple[str, AccountType, NormalSide]] = {
    "INCOME_CONTROL": (
        "Income Control",
        AccountType.INCOME,
        NormalSide.CREDIT,
    ),
    "EXPENSE_CONTROL": (
        "Expense Control",
        AccountType.EXPENSE,
        NormalSide.DEBIT,
    ),
    "OPENING_BALANCE_EQUITY": (
        "Opening Balance Equity",
        AccountType.EQUITY,
        NormalSide.CREDIT,
    ),
}


def ensure_system_accounts(
    db: Session, user_id: uuid.UUID
) -> dict[str, LedgerAccount]:
    """Pastikan tiga akun kontrol milik user ada. Idempotent dan aman
    dipanggil bersamaan: konflik ditangani unique constraint database."""
    for code, (name, account_type, side) in SYSTEM_ACCOUNTS.items():
        db.execute(
            pg_insert(LedgerAccount)
            .values(
                user_id=user_id,
                account_code=code,
                account_name=name,
                account_type=account_type.value,
                normal_side=side.value,
                currency=CURRENCY,
                is_system=True,
            )
            .on_conflict_do_nothing(
                constraint="uq_ledger_accounts_user_id_account_code"
            )
        )
    accounts = (
        db.execute(
            select(LedgerAccount).where(
                LedgerAccount.user_id == user_id,
                LedgerAccount.is_system.is_(True),
            )
        )
        .scalars()
        .all()
    )
    return {account.account_code: account for account in accounts}


def create_wallet_asset_account(
    db: Session,
    *,
    user_id: uuid.UUID,
    wallet_id: uuid.UUID,
    name: str,
    currency: str = CURRENCY,
) -> LedgerAccount:
    account = LedgerAccount(
        user_id=user_id,
        wallet_id=wallet_id,
        account_code=f"WALLET:{wallet_id}",
        account_name=name,
        account_type=AccountType.ASSET.value,
        normal_side=NormalSide.DEBIT.value,
        currency=currency,
        is_system=False,
    )
    db.add(account)
    db.flush()
    return account

def rename_wallet_account(
    db: Session, *, user_id: uuid.UUID, wallet_id: uuid.UUID, name: str
) -> None:
    """Samakan nama akun ledger dengan nama wallet. Tanpa commit."""
    db.execute(
        update(LedgerAccount)
        .where(
            LedgerAccount.wallet_id == wallet_id,
            LedgerAccount.user_id == user_id,
        )
        .values(account_name=name)
    )
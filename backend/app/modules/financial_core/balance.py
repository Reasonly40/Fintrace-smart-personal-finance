import uuid

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.modules.financial_core.enums import EntryType
from app.modules.financial_core.models import LedgerAccount, LedgerEntry


def wallet_balance(
    db: Session, *, user_id: uuid.UUID, wallet_id: uuid.UUID
) -> int:
    """Saldo = debit - kredit pada akun ASSET wallet (bagian 7.4).

    Entries hanya ada untuk jurnal yang sudah diposting, termasuk jurnal
    reversal, jadi DRAFT otomatis tidak memengaruhi saldo.
    """
    signed = case(
        (LedgerEntry.entry_type == EntryType.DEBIT.value, LedgerEntry.amount),
        else_=-LedgerEntry.amount,
    )
    total = db.execute(
        select(func.coalesce(func.sum(signed), 0))
        .select_from(LedgerEntry)
        .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
        .where(
            LedgerAccount.wallet_id == wallet_id,
            LedgerAccount.user_id == user_id,
        )
    ).scalar_one()
    return int(total)
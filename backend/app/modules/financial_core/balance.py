import uuid

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.modules.financial_core.enums import EntryType
from app.modules.financial_core.models import LedgerAccount, LedgerEntry


def wallet_balances(
    db: Session, *, user_id: uuid.UUID, wallet_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Saldo beberapa wallet sekaligus dalam satu query.

    Saldo = debit - kredit pada akun ASSET wallet (bagian 7.4). Entries
    hanya ada untuk jurnal yang sudah diposting, termasuk jurnal reversal,
    jadi DRAFT otomatis tidak memengaruhi saldo.
    """
    result = dict.fromkeys(wallet_ids, 0)
    if not wallet_ids:
        return result

    signed = case(
        (LedgerEntry.entry_type == EntryType.DEBIT.value, LedgerEntry.amount),
        else_=-LedgerEntry.amount,
    )
    rows = db.execute(
        select(LedgerAccount.wallet_id, func.coalesce(func.sum(signed), 0))
        .select_from(LedgerEntry)
        .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
        .where(
            LedgerAccount.user_id == user_id,
            LedgerAccount.wallet_id.in_(wallet_ids),
        )
        .group_by(LedgerAccount.wallet_id)
    ).all()
    for wallet_id, total in rows:
        result[wallet_id] = int(total)
    return result


def wallet_balance(
    db: Session, *, user_id: uuid.UUID, wallet_id: uuid.UUID
) -> int:
    return wallet_balances(db, user_id=user_id, wallet_ids=[wallet_id])[
        wallet_id
    ]
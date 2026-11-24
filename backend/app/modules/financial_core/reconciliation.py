import uuid
from dataclasses import dataclass

from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.orm import Session

from app.modules.financial_core.balance import wallet_balances
from app.modules.financial_core.enums import AccountType, EntryType
from app.modules.financial_core.models import (
    LedgerAccount,
    LedgerEntry,
    Transaction,
)
from app.modules.wallet.models import Wallet

POSTED_STATUSES = ("POSTED", "REVERSED")


def _sum_side(side: EntryType):
    return func.coalesce(
        func.sum(
            case((LedgerEntry.entry_type == side.value, LedgerEntry.amount), else_=0)
        ),
        0,
    )


@dataclass(frozen=True)
class ReconciliationReport:
    """Hasil pemeriksaan seluruh ledger milik satu user."""

    total_debit: int
    total_credit: int
    assets: int
    income: int
    expense: int
    equity: int
    balances: dict[uuid.UUID, int]
    unbalanced_transactions: tuple[uuid.UUID, ...]
    transactions_without_entries: tuple[uuid.UUID, ...]
    negative_wallets: tuple[uuid.UUID, ...]

    @property
    def equation_holds(self) -> bool:
        """Persamaan akuntansi: Aset = Pendapatan + Ekuitas - Beban."""
        return self.assets == self.income + self.equity - self.expense

    @property
    def is_consistent(self) -> bool:
        return (
            self.total_debit == self.total_credit
            and self.equation_holds
            and self.assets == sum(self.balances.values())
            and not self.unbalanced_transactions
            and not self.transactions_without_entries
            and not self.negative_wallets
        )


def reconcile_user(db: Session, *, user_id: uuid.UUID) -> ReconciliationReport:
    debit = _sum_side(EntryType.DEBIT)
    credit = _sum_side(EntryType.CREDIT)

    # Total debit dan kredit per tipe akun
    rows = db.execute(
        select(LedgerAccount.account_type, debit, credit)
        .select_from(LedgerEntry)
        .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
        .where(LedgerEntry.user_id == user_id)
        .group_by(LedgerAccount.account_type)
    ).all()
    totals = {kind: (int(d), int(c)) for kind, d, c in rows}

    def net_debit(kind: AccountType) -> int:
        d, c = totals.get(kind.value, (0, 0))
        return d - c

    # Transaksi yang jurnalnya tidak sama dengan nominal header
    unbalanced = (
        db.execute(
            select(Transaction.id)
            .join(LedgerEntry, LedgerEntry.transaction_id == Transaction.id)
            .where(Transaction.user_id == user_id)
            .group_by(Transaction.id, Transaction.amount)
            .having(
                or_(debit != Transaction.amount, credit != Transaction.amount)
            )
        )
        .scalars()
        .all()
    )

    # Transaksi POSTED atau REVERSED yang tidak punya entries
    without_entries = (
        db.execute(
            select(Transaction.id).where(
                Transaction.user_id == user_id,
                Transaction.status.in_(POSTED_STATUSES),
                ~exists().where(LedgerEntry.transaction_id == Transaction.id),
            )
        )
        .scalars()
        .all()
    )

    wallet_ids = (
        db.execute(select(Wallet.id).where(Wallet.user_id == user_id))
        .scalars()
        .all()
    )
    balances = wallet_balances(db, user_id=user_id, wallet_ids=list(wallet_ids))

    return ReconciliationReport(
        total_debit=sum(d for d, _ in totals.values()),
        total_credit=sum(c for _, c in totals.values()),
        assets=net_debit(AccountType.ASSET),
        income=-net_debit(AccountType.INCOME),
        expense=net_debit(AccountType.EXPENSE),
        equity=-net_debit(AccountType.EQUITY),
        balances=balances,
        unbalanced_transactions=tuple(sorted(unbalanced)),
        transactions_without_entries=tuple(sorted(without_entries)),
        negative_wallets=tuple(
            sorted(wid for wid, balance in balances.items() if balance < 0)
        ),
    )
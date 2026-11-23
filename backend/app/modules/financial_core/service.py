import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.modules.financial_core.balance import wallet_balance
from app.modules.financial_core.enums import (
    AccountType,
    NormalSide,
    TransactionStatus,
    TransactionType,
)
from app.modules.financial_core.errors import (
    InsufficientBalanceError,
    InvalidAmountError,
    InvalidDateRangeError,
    InvalidTransactionShapeError,
    OpeningBalanceNotAllowedError,
    SameWalletTransferError,
    TransactionNotDraftError,
    TransactionNotFoundError,
    UnsupportedTransactionTypeError,
    WalletNotActiveError,
)
from app.modules.financial_core.journal import JournalAccounts, build_journal
from app.modules.financial_core.models import (
    LedgerAccount,
    LedgerEntry,
    Transaction,
)
from app.modules.operations import service as idempotency
from app.modules.wallet.errors import WalletNotFoundError
from app.modules.wallet.models import Wallet

CURRENCY = "IDR"

# Tipe yang bisa dibuat dan diposting sekarang; REVERSAL menyusul di 2.7
POSTABLE_TYPES = {
    TransactionType.INCOME,
    TransactionType.EXPENSE,
    TransactionType.OPENING_BALANCE,
    TransactionType.TRANSFER,
}

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


@dataclass(frozen=True)
class PostResult:
    transaction_id: uuid.UUID
    replayed: bool


# ---------- akun ----------


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


# ---------- transaksi ----------


def create_draft(
    db: Session,
    *,
    user_id: uuid.UUID,
    transaction_type: TransactionType,
    amount: int,
    occurred_at: datetime,
    wallet_id: uuid.UUID | None = None,
    from_wallet_id: uuid.UUID | None = None,
    to_wallet_id: uuid.UUID | None = None,
    description: str | None = None,
) -> Transaction:
    """Buat transaksi DRAFT. DRAFT tidak punya entries dan tidak memengaruhi
    saldo. Tanpa commit."""
    if transaction_type not in POSTABLE_TYPES:
        raise UnsupportedTransactionTypeError()
    if amount <= 0:
        raise InvalidAmountError()

    if transaction_type == TransactionType.TRANSFER:
        if (
            wallet_id is not None
            or from_wallet_id is None
            or to_wallet_id is None
        ):
            raise InvalidTransactionShapeError()
        if from_wallet_id == to_wallet_id:
            raise SameWalletTransferError()
        wanted = [from_wallet_id, to_wallet_id]
    else:
        if (
            wallet_id is None
            or from_wallet_id is not None
            or to_wallet_id is not None
        ):
            raise InvalidTransactionShapeError()
        wanted = [wallet_id]

    wallets = (
        db.execute(
            select(Wallet).where(
                Wallet.id.in_(wanted), Wallet.user_id == user_id
            )
        )
        .scalars()
        .all()
    )
    # Wallet asing dan wallet yang tidak ada tidak dibedakan
    if len(wallets) != len(wanted):
        raise WalletNotFoundError()
    if any(not wallet.is_active for wallet in wallets):
        raise WalletNotActiveError()

    transaction = Transaction(
        user_id=user_id,
        transaction_type=transaction_type.value,
        amount=Decimal(amount),
        currency=CURRENCY,
        wallet_id=wallet_id,
        from_wallet_id=from_wallet_id,
        to_wallet_id=to_wallet_id,
        description=description,
        occurred_at=occurred_at,
    )
    db.add(transaction)
    db.flush()
    return transaction

def _wallet_has_entries(
    db: Session, *, user_id: uuid.UUID, wallet_id: uuid.UUID
) -> bool:
    row = db.execute(
        select(LedgerEntry.id)
        .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
        .where(
            LedgerAccount.wallet_id == wallet_id,
            LedgerAccount.user_id == user_id,
        )
        .limit(1)
    ).first()
    return row is not None

def _lock_wallets(
    db: Session, *, user_id: uuid.UUID, wallet_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Wallet]:
    """Kunci wallet dengan SELECT FOR UPDATE dalam urutan ID yang tetap.

    Urutan yang sama di semua jalur mencegah deadlock ketika dua transfer
    bolak-balik antara wallet yang sama berjalan bersamaan (bagian 9.4).
    """
    ids = sorted(set(wallet_ids))
    rows = (
        db.execute(
            select(Wallet)
            .where(Wallet.id.in_(ids), Wallet.user_id == user_id)
            .order_by(Wallet.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        .scalars()
        .all()
    )
    if len(rows) != len(ids):
        raise WalletNotFoundError()
    return {wallet.id: wallet for wallet in rows}


def _journal_accounts(
    db: Session, *, user_id: uuid.UUID, transaction: Transaction
) -> JournalAccounts:
    wallet_ids = [
        wallet_id
        for wallet_id in (
            transaction.wallet_id,
            transaction.from_wallet_id,
            transaction.to_wallet_id,
        )
        if wallet_id is not None
    ]
    rows = db.execute(
        select(LedgerAccount.wallet_id, LedgerAccount.id).where(
            LedgerAccount.user_id == user_id,
            LedgerAccount.wallet_id.in_(wallet_ids),
        )
    ).all()
    by_wallet = {wallet_id: account_id for wallet_id, account_id in rows}
    system = ensure_system_accounts(db, user_id)
    return JournalAccounts(
        income_control_id=system["INCOME_CONTROL"].id,
        expense_control_id=system["EXPENSE_CONTROL"].id,
        opening_equity_id=system["OPENING_BALANCE_EQUITY"].id,
        wallet_account_id=by_wallet.get(transaction.wallet_id),
        from_account_id=by_wallet.get(transaction.from_wallet_id),
        to_account_id=by_wallet.get(transaction.to_wallet_id),
    )


def post_transaction(
    db: Session, *, user_id: uuid.UUID, transaction_id: uuid.UUID
) -> Transaction:
    """Posting DRAFT menjadi POSTED beserta jurnalnya (bagian 9.3).

    Tanpa commit: pemanggil memegang batas transaksi database, sehingga
    header, jurnal, status, dan hasil idempotency commit atau batal bersama.
    """
    transaction = db.execute(
        select(Transaction)
        .where(
            Transaction.id == transaction_id, Transaction.user_id == user_id
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if transaction is None:
        raise TransactionNotFoundError()
    if transaction.status != TransactionStatus.DRAFT:
        raise TransactionNotDraftError()

    kind = TransactionType(transaction.transaction_type)
    if kind not in POSTABLE_TYPES:
        raise UnsupportedTransactionTypeError()

    if kind == TransactionType.TRANSFER:
        primary_wallet_id = transaction.from_wallet_id
        wallet_ids = [transaction.from_wallet_id, transaction.to_wallet_id]
    else:
        primary_wallet_id = transaction.wallet_id
        wallet_ids = [transaction.wallet_id]

    # Kunci SEMUA wallet yang terdampak, dalam urutan ID yang tetap, sebelum
    # memeriksa saldo. Status aktif dibaca ulang setelah lock didapat.
    wallets = _lock_wallets(db, user_id=user_id, wallet_ids=wallet_ids)
    if any(not wallet.is_active for wallet in wallets.values()):
        raise WalletNotActiveError()

    amount = int(transaction.amount)
    if kind in (TransactionType.EXPENSE, TransactionType.TRANSFER):
        # Untuk transfer yang diperiksa hanya saldo asal (FIN-007)
        balance = wallet_balance(
            db, user_id=user_id, wallet_id=primary_wallet_id
        )
        if balance < amount:
            raise InsufficientBalanceError()
    if kind == TransactionType.OPENING_BALANCE and _wallet_has_entries(
        db, user_id=user_id, wallet_id=primary_wallet_id
    ):
        raise OpeningBalanceNotAllowedError()

    accounts = _journal_accounts(db, user_id=user_id, transaction=transaction)
    lines = build_journal(transaction.transaction_type, amount, accounts)

    transaction.status = TransactionStatus.POSTED.value
    transaction.posted_at = datetime.now(UTC)
    db.flush()
    for line in lines:
        db.add(
            LedgerEntry(
                user_id=user_id,
                transaction_id=transaction.id,
                account_id=line.account_id,
                entry_type=line.entry_type.value,
                amount=Decimal(line.amount),
            )
        )
    db.flush()
    return transaction


def post_with_idempotency(
    db: Session,
    *,
    user_id: uuid.UUID,
    transaction_id: uuid.UUID,
    idempotency_key: str,
) -> PostResult:
    """Posting yang aman diulang. Commit dilakukan di sini, sekali, untuk
    posting dan record idempotency sekaligus (FIN-012)."""
    fingerprint = idempotency.request_fingerprint(
        "transactions.post", {"transaction_id": str(transaction_id)}
    )
    try:
        outcome = idempotency.begin(
            db,
            user_id=user_id,
            key=idempotency_key,
            request_hash=fingerprint,
        )
        if outcome.replayed:
            stored = outcome.response or {}
            return PostResult(
                transaction_id=uuid.UUID(stored["transaction_id"]),
                replayed=True,
            )
        transaction = post_transaction(
            db, user_id=user_id, transaction_id=transaction_id
        )
        idempotency.complete(
            db,
            outcome.record,
            {
                "transaction_id": str(transaction.id),
                "status": transaction.status,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return PostResult(transaction_id=transaction.id, replayed=False)

# ---------- baca, daftar, dan pembuatan idempoten ----------

TxSortField = Literal["occurred_at", "amount", "created_at"]
TxSortOrder = Literal["asc", "desc"]

# Allowlist kolom pengurutan: nilai dari klien tidak pernah masuk ke SQL
TX_SORT_COLUMNS = {
    "occurred_at": Transaction.occurred_at,
    "amount": Transaction.amount,
    "created_at": Transaction.created_at,
}


@dataclass(frozen=True)
class CreateResult:
    transaction_id: uuid.UUID
    replayed: bool


def get_transaction(
    db: Session, *, user_id: uuid.UUID, transaction_id: uuid.UUID
) -> Transaction:
    """Transaksi milik user. Kepemilikan dicek di dalam query itu sendiri,
    jadi transaksi orang lain sama saja dengan transaksi yang tidak ada."""
    transaction = db.execute(
        select(Transaction).where(
            Transaction.id == transaction_id, Transaction.user_id == user_id
        )
    ).scalar_one_or_none()
    if transaction is None:
        raise TransactionNotFoundError()
    return transaction


def get_transaction_entries(
    db: Session, *, user_id: uuid.UUID, transaction_id: uuid.UUID
) -> list[tuple[LedgerEntry, LedgerAccount]]:
    rows = db.execute(
        select(LedgerEntry, LedgerAccount)
        .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
        .where(
            LedgerEntry.transaction_id == transaction_id,
            LedgerEntry.user_id == user_id,
        )
        # DEBIT lebih dulu, lalu CREDIT
        .order_by(LedgerEntry.entry_type.desc(), LedgerEntry.id)
    ).all()
    return [(entry, account) for entry, account in rows]


def _check_range(
    occurred_from: datetime | None, occurred_to: datetime | None
) -> None:
    for value in (occurred_from, occurred_to):
        if value is not None and value.tzinfo is None:
            raise InvalidDateRangeError(
                "Waktu harus menyertakan zona waktu, misalnya akhiran Z."
            )
    if (
        occurred_from is not None
        and occurred_to is not None
        and occurred_from >= occurred_to
    ):
        raise InvalidDateRangeError()


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_transactions(
    db: Session,
    *,
    user_id: uuid.UUID,
    wallet_id: uuid.UUID | None = None,
    transaction_type: TransactionType | None = None,
    status: TransactionStatus | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    search: str | None = None,
    sort: TxSortField = "occurred_at",
    order: TxSortOrder = "desc",
    page: int = 1,
    limit: int = 20,
) -> tuple[list[Transaction], int]:
    _check_range(occurred_from, occurred_to)

    conditions = [Transaction.user_id == user_id]
    if wallet_id is not None:
        conditions.append(
            or_(
                Transaction.wallet_id == wallet_id,
                Transaction.from_wallet_id == wallet_id,
                Transaction.to_wallet_id == wallet_id,
            )
        )
    if transaction_type is not None:
        conditions.append(Transaction.transaction_type == transaction_type.value)
    if status is not None:
        conditions.append(Transaction.status == status.value)
    if occurred_from is not None:
        conditions.append(Transaction.occurred_at >= occurred_from)
    if occurred_to is not None:
        conditions.append(Transaction.occurred_at < occurred_to)
    search = search.strip() if search else None
    if search:
        conditions.append(
            Transaction.description.ilike(
                f"%{_escape_like(search)}%", escape="\\"
            )
        )

    total = db.execute(
        select(func.count()).select_from(Transaction).where(*conditions)
    ).scalar_one()

    column = TX_SORT_COLUMNS[sort]
    ordering = column.asc() if order == "asc" else column.desc()
    rows = (
        db.execute(
            select(Transaction)
            .where(*conditions)
            # id sebagai penentu akhir agar halaman stabil
            .order_by(ordering, Transaction.id)
            .limit(limit)
            .offset((page - 1) * limit)
        )
        .scalars()
        .all()
    )
    return list(rows), total


def create_draft_with_idempotency(
    db: Session,
    *,
    user_id: uuid.UUID,
    idempotency_key: str | None,
    transaction_type: TransactionType,
    amount: int,
    occurred_at: datetime,
    wallet_id: uuid.UUID | None = None,
    from_wallet_id: uuid.UUID | None = None,
    to_wallet_id: uuid.UUID | None = None,
    description: str | None = None,
) -> CreateResult:
    """Buat draft; bila ada key, aman diulang. Commit dilakukan di sini."""
    try:
        record = None
        if idempotency_key is not None:
            fingerprint = idempotency.request_fingerprint(
                "transactions.create",
                {
                    "transaction_type": transaction_type.value,
                    "amount": amount,
                    "wallet_id": str(wallet_id) if wallet_id else None,
                    "from_wallet_id": (
                        str(from_wallet_id) if from_wallet_id else None
                    ),
                    "to_wallet_id": (
                        str(to_wallet_id) if to_wallet_id else None
                    ),
                    "occurred_at": occurred_at.isoformat(),
                    "description": description,
                },
            )
            outcome = idempotency.begin(
                db,
                user_id=user_id,
                key=idempotency_key,
                request_hash=fingerprint,
            )
            if outcome.replayed:
                stored = outcome.response or {}
                return CreateResult(
                    transaction_id=uuid.UUID(stored["transaction_id"]),
                    replayed=True,
                )
            record = outcome.record

        transaction = create_draft(
            db,
            user_id=user_id,
            transaction_type=transaction_type,
            amount=amount,
            occurred_at=occurred_at,
            wallet_id=wallet_id,
            from_wallet_id=from_wallet_id,
            to_wallet_id=to_wallet_id,
            description=description,
        )
        if record is not None:
            idempotency.complete(
                db, record, {"transaction_id": str(transaction.id)}
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return CreateResult(transaction_id=transaction.id, replayed=False)
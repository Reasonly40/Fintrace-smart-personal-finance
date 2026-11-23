import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, update
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
    OpeningBalanceNotAllowedError,
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

# Tipe yang bisa dibuat dan diposting sekarang; TRANSFER (2.6), REVERSAL (2.7)
POSTABLE_TYPES = {
    TransactionType.INCOME,
    TransactionType.EXPENSE,
    TransactionType.OPENING_BALANCE,
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
    wallet_id: uuid.UUID,
    occurred_at: datetime,
    description: str | None = None,
) -> Transaction:
    """Buat transaksi DRAFT. DRAFT tidak punya entries dan tidak memengaruhi
    saldo. Tanpa commit."""
    if transaction_type not in POSTABLE_TYPES:
        raise UnsupportedTransactionTypeError()
    if amount <= 0:
        raise InvalidAmountError()

    wallet = db.execute(
        select(Wallet).where(Wallet.id == wallet_id, Wallet.user_id == user_id)
    ).scalar_one_or_none()
    if wallet is None:
        raise WalletNotFoundError()
    if not wallet.is_active:
        raise WalletNotActiveError()

    transaction = Transaction(
        user_id=user_id,
        transaction_type=transaction_type.value,
        amount=Decimal(amount),
        currency=wallet.currency,
        wallet_id=wallet.id,
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


def _journal_accounts(
    db: Session, *, user_id: uuid.UUID, wallet_id: uuid.UUID
) -> JournalAccounts:
    wallet_account_id = db.execute(
        select(LedgerAccount.id).where(
            LedgerAccount.wallet_id == wallet_id,
            LedgerAccount.user_id == user_id,
        )
    ).scalar_one()
    system = ensure_system_accounts(db, user_id)
    return JournalAccounts(
        wallet_account_id=wallet_account_id,
        income_control_id=system["INCOME_CONTROL"].id,
        expense_control_id=system["EXPENSE_CONTROL"].id,
        opening_equity_id=system["OPENING_BALANCE_EQUITY"].id,
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

    # Kunci wallet SEBELUM memeriksa saldo; baca ulang statusnya setelah
    # lock didapat supaya tidak memakai data usang.
    wallet = db.execute(
        select(Wallet)
        .where(Wallet.id == transaction.wallet_id, Wallet.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    if not wallet.is_active:
        raise WalletNotActiveError()

    amount = int(transaction.amount)
    if kind == TransactionType.EXPENSE:
        balance = wallet_balance(db, user_id=user_id, wallet_id=wallet.id)
        if balance < amount:
            raise InsufficientBalanceError()
    if kind == TransactionType.OPENING_BALANCE and _wallet_has_entries(
        db, user_id=user_id, wallet_id=wallet.id
    ):
        raise OpeningBalanceNotAllowedError()

    accounts = _journal_accounts(db, user_id=user_id, wallet_id=wallet.id)
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
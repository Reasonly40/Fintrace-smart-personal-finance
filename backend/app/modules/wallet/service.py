import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.financial_core import service as ledger_service
from app.modules.wallet.enums import WalletType
from app.modules.wallet.errors import (
    WalletAlreadyArchivedError,
    WalletArchivedError,
    WalletNotFoundError,
)
from app.modules.wallet.models import Wallet

StatusFilter = Literal["active", "archived", "all"]
SortField = Literal["created_at", "name"]
SortOrder = Literal["asc", "desc"]

# Allowlist kolom pengurutan: nilai dari klien tidak pernah masuk ke SQL
SORT_COLUMNS = {"created_at": Wallet.created_at, "name": Wallet.name}


def create_wallet(
    db: Session, *, user_id: uuid.UUID, name: str, wallet_type: WalletType
) -> Wallet:
    """Buat wallet beserta akun ASSET-nya dalam satu transaksi database.

    Gagal di mana pun berarti tidak ada yang tersimpan (FIN-004, FIN-012).
    """
    wallet = Wallet(
        user_id=user_id, name=name.strip(), wallet_type=wallet_type.value
    )
    try:
        db.add(wallet)
        db.flush()
        ledger_service.create_wallet_asset_account(
            db,
            user_id=user_id,
            wallet_id=wallet.id,
            name=wallet.name,
            currency=wallet.currency,
        )
        ledger_service.ensure_system_accounts(db, user_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(wallet)
    return wallet


def get_wallet(
    db: Session,
    *,
    user_id: uuid.UUID,
    wallet_id: uuid.UUID,
    for_update: bool = False,
) -> Wallet:
    """Wallet milik user. Kepemilikan dicek di dalam query itu sendiri,
    jadi wallet orang lain sama saja dengan wallet yang tidak ada."""
    query = select(Wallet).where(
        Wallet.id == wallet_id, Wallet.user_id == user_id
    )
    if for_update:
        query = query.with_for_update()
    wallet = db.execute(query).scalar_one_or_none()
    if wallet is None:
        raise WalletNotFoundError()
    return wallet


def list_wallets(
    db: Session,
    *,
    user_id: uuid.UUID,
    status: StatusFilter = "active",
    wallet_type: WalletType | None = None,
    sort: SortField = "created_at",
    order: SortOrder = "desc",
    page: int = 1,
    limit: int = 20,
) -> tuple[list[Wallet], int]:
    conditions = [Wallet.user_id == user_id]
    if status == "active":
        conditions.append(Wallet.is_active.is_(True))
    elif status == "archived":
        conditions.append(Wallet.is_active.is_(False))
    if wallet_type is not None:
        conditions.append(Wallet.wallet_type == wallet_type.value)

    total = db.execute(
        select(func.count()).select_from(Wallet).where(*conditions)
    ).scalar_one()

    column = SORT_COLUMNS[sort]
    ordering = column.asc() if order == "asc" else column.desc()
    rows = (
        db.execute(
            select(Wallet)
            .where(*conditions)
            # id sebagai penentu akhir agar halaman stabil
            .order_by(ordering, Wallet.id)
            .limit(limit)
            .offset((page - 1) * limit)
        )
        .scalars()
        .all()
    )
    return list(rows), total


def update_wallet(
    db: Session,
    *,
    user_id: uuid.UUID,
    wallet_id: uuid.UUID,
    name: str | None,
    wallet_type: WalletType | None,
) -> Wallet:
    wallet = get_wallet(
        db, user_id=user_id, wallet_id=wallet_id, for_update=True
    )
    if not wallet.is_active:
        raise WalletArchivedError()
    try:
        if name is not None:
            wallet.name = name
            ledger_service.rename_wallet_account(
                db, user_id=user_id, wallet_id=wallet.id, name=name
            )
        if wallet_type is not None:
            wallet.wallet_type = wallet_type.value
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(wallet)
    return wallet


def archive_wallet(
    db: Session, *, user_id: uuid.UUID, wallet_id: uuid.UUID
) -> Wallet:
    wallet = get_wallet(
        db, user_id=user_id, wallet_id=wallet_id, for_update=True
    )
    if not wallet.is_active:
        raise WalletAlreadyArchivedError()
    try:
        wallet.is_active = False
        wallet.archived_at = datetime.now(UTC)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(wallet)
    return wallet
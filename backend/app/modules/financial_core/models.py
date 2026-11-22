import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mixins import UUIDPrimaryKeyMixin
from app.db.session import Base
from app.db.sql import sql_in
from app.modules.financial_core.enums import AccountType, NormalSide


class LedgerAccount(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ledger_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # NULL untuk akun sistem; FK-nya composite (lihat __table_args__)
    wallet_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    account_code: Mapped[str] = mapped_column(String(50), nullable=False)
    account_name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_type: Mapped[str] = mapped_column(String(10), nullable=False)
    normal_side: Mapped[str] = mapped_column(String(6), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="IDR", server_default=text("'IDR'")
    )
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # FIN-005: akun hanya boleh menunjuk wallet milik user yang sama.
        # Bila wallet_id NULL (akun sistem), constraint ini tidak dicek.
        ForeignKeyConstraint(
            ["wallet_id", "user_id"],
            ["wallets.id", "wallets.user_id"],
            ondelete="RESTRICT",
        ),
        # FIN-004 (bagian "paling banyak satu")
        UniqueConstraint("wallet_id", name="uq_ledger_accounts_wallet_id"),
        UniqueConstraint(
            "user_id",
            "account_code",
            name="uq_ledger_accounts_user_id_account_code",
        ),
        # Diperlukan untuk composite FK dari ledger_entries nanti
        UniqueConstraint("id", "user_id", name="uq_ledger_accounts_id_user_id"),
        CheckConstraint(sql_in("account_type", AccountType), name="type_valid"),
        CheckConstraint(sql_in("normal_side", NormalSide), name="side_valid"),
        CheckConstraint(
            "(account_type IN ('ASSET', 'EXPENSE') AND normal_side = 'DEBIT') "
            "OR (account_type IN ('INCOME', 'EQUITY') "
            "AND normal_side = 'CREDIT')",
            name="normal_side_matches_type",
        ),
        CheckConstraint(
            "(account_type = 'ASSET' AND wallet_id IS NOT NULL "
            "AND NOT is_system) "
            "OR (account_type <> 'ASSET' AND wallet_id IS NULL AND is_system)",
            name="wallet_link",
        ),
        CheckConstraint("currency = 'IDR'", name="currency_idr"),
        Index("ix_ledger_accounts_user_id", "user_id"),
    )
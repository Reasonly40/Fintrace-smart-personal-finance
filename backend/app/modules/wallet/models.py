import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.session import Base
from app.db.sql import sql_in
from app.modules.wallet.enums import WalletType


class Wallet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wallets"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    wallet_type: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="IDR", server_default=text("'IDR'")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # Diperlukan agar tabel lain bisa memakai composite FK (id, user_id)
        UniqueConstraint("id", "user_id", name="uq_wallets_id_user_id"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint(sql_in("wallet_type", WalletType), name="type_valid"),
        CheckConstraint("currency = 'IDR'", name="currency_idr"),
        CheckConstraint(
            "(is_active AND archived_at IS NULL) "
            "OR (NOT is_active AND archived_at IS NOT NULL)",
            name="archive_consistent",
        ),
        Index("ix_wallets_user_id", "user_id"),
    )
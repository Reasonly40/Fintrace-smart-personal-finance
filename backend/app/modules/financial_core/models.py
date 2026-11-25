import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.session import Base
from app.db.sql import sql_in
from app.modules.financial_core.enums import (
    AccountType,
    EntryType,
    NormalSide,
    TransactionStatus,
    TransactionType,
)


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

class Transaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "transactions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 0), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="IDR", server_default=text("'IDR'")
    )
    # FK composite (lihat __table_args__), semuanya nullable sesuai tipe
    wallet_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    from_wallet_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True
    )
    to_wallet_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=TransactionStatus.DRAFT.value,
        server_default=text("'DRAFT'"),
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        # FIN-005: transaksi hanya boleh menunjuk wallet milik user yang sama
        ForeignKeyConstraint(
            ["wallet_id", "user_id"],
            ["wallets.id", "wallets.user_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["from_wallet_id", "user_id"],
            ["wallets.id", "wallets.user_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["to_wallet_id", "user_id"],
            ["wallets.id", "wallets.user_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["reversal_of_id", "user_id"],
            ["transactions.id", "transactions.user_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "user_id", name="uq_transactions_id_user_id"),
        # FIN-009: satu transaksi paling banyak punya satu reversal
        UniqueConstraint("reversal_of_id", name="uq_transactions_reversal_of_id"),
        CheckConstraint(
            sql_in("transaction_type", TransactionType), name="type_valid"
        ),
        CheckConstraint(sql_in("status", TransactionStatus), name="status_valid"),
        # FIN-010
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("currency = 'IDR'", name="currency_idr"),
        # Bagian 8.6: struktur wallet menurut tipe transaksi
        CheckConstraint(
            "(transaction_type IN ('INCOME', 'EXPENSE', 'OPENING_BALANCE') "
            "AND wallet_id IS NOT NULL AND from_wallet_id IS NULL "
            "AND to_wallet_id IS NULL) "
            "OR (transaction_type = 'TRANSFER' AND wallet_id IS NULL "
            "AND from_wallet_id IS NOT NULL AND to_wallet_id IS NOT NULL) "
            "OR (transaction_type = 'REVERSAL' AND wallet_id IS NULL "
            "AND from_wallet_id IS NULL AND to_wallet_id IS NULL)",
            name="structure_by_type",
        ),
        # FIN-006 (bernilai NULL, dan lolos, untuk tipe selain TRANSFER)
        CheckConstraint(
            "from_wallet_id <> to_wallet_id", name="transfer_wallets_differ"
        ),
        CheckConstraint(
            "(transaction_type = 'REVERSAL') = (reversal_of_id IS NOT NULL)",
            name="reversal_link",
        ),
        CheckConstraint(
            "transaction_type <> 'REVERSAL' OR status = 'POSTED'",
            name="reversal_is_posted",
        ),
        CheckConstraint(
            "(status = 'DRAFT' AND posted_at IS NULL) "
            "OR (status IN ('POSTED', 'REVERSED') AND posted_at IS NOT NULL)",
            name="posted_at_matches_status",
        ),
                # Hanya income dan expense yang memakai kategori (bagian 8.6)
        CheckConstraint(
            "category_id IS NULL OR transaction_type IN ('INCOME', 'EXPENSE')",
            name="category_only_income_expense",
        ),
        Index(
            "ix_transactions_user_id_category_id_occurred_at",
            "user_id",
            "category_id",
            "occurred_at",
        ),
        # Bagian 8.7
        Index("ix_transactions_user_id_occurred_at", "user_id", "occurred_at"),
        Index("ix_transactions_user_id_status", "user_id", "status"),
        # Bagian 7.6: satu opening balance aktif per wallet
        Index(
            "uq_transactions_opening_balance_wallet",
            "wallet_id",
            unique=True,
            postgresql_where=text(
                "transaction_type = 'OPENING_BALANCE' AND status <> 'REVERSED'"
            ),
        ),
    )


class LedgerEntry(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ledger_entries"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    entry_type: Mapped[str] = mapped_column(String(6), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 0), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Bagian 8.5: entry, transaksi, dan akun wajib milik user yang sama
        ForeignKeyConstraint(
            ["transaction_id", "user_id"],
            ["transactions.id", "transactions.user_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["ledger_accounts.id", "ledger_accounts.user_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(sql_in("entry_type", EntryType), name="type_valid"),
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_ledger_entries_transaction_id", "transaction_id"),
        Index(
            "ix_ledger_entries_account_id_created_at",
            "account_id",
            "created_at",
        ),
    )
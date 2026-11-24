import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mixins import UUIDPrimaryKeyMixin
from app.db.session import Base
from app.db.sql import sql_in
from app.modules.operations.enums import IdempotencyStatus


class IdempotencyRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "idempotency_records"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        default=IdempotencyStatus.PROCESSING.value,
        server_default=text("'PROCESSING'"),
    )
    response_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_idempotency_records_user_id_idempotency_key",
        ),
        CheckConstraint(sql_in("status", IdempotencyStatus), name="status_valid"),
        CheckConstraint(
            "length(btrim(idempotency_key)) > 0", name="key_not_blank"
        ),
        CheckConstraint(
            "(status = 'PROCESSING' AND response_data IS NULL) "
            "OR (status = 'COMPLETED' AND response_data IS NOT NULL)",
            name="response_matches_status",
        ),
        Index("ix_idempotency_records_expires_at", "expires_at"),
    )

class AuditLog(UUIDPrimaryKeyMixin, Base):
    """Jejak aktivitas penting. Hanya bisa ditambah, tidak bisa diubah."""

    __tablename__ = "audit_logs"

    # NULL untuk kejadian tanpa pengguna terkenal (misalnya login gagal
    # dengan email yang tidak terdaftar)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # Atribut bernama event_metadata karena `metadata` dipakai SQLAlchemy;
    # nama kolom di database tetap `metadata` sesuai dokumen
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("length(btrim(action)) > 0", name="action_not_blank"),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object'", name="metadata_is_object"
        ),
        Index("ix_audit_logs_user_id_created_at", "user_id", "created_at"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
    )
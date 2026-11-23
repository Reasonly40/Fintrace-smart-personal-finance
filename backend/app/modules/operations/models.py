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
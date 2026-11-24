import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezones import DEFAULT_TIMEZONE
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.session import Base


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=DEFAULT_TIMEZONE,
        server_default=text("'Asia/Makassar'"),
    )
    __table_args__ = (
        UniqueConstraint("email"),
        # Email wajib disimpan huruf kecil; service juga menormalisasinya
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("length(btrim(timezone)) > 0", name="timezone_not_blank"),
    )


class UserSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Yang disimpan hanya hash token, bukan token mentah (NFR-01)
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

class LoginAttempt(UUIDPrimaryKeyMixin, Base):
    """Catatan login gagal untuk rate limit. Email disimpan sebagai HMAC."""

    __tablename__ = "login_attempts"

    email_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_login_attempts_email_ip_time",
            "email_hash",
            "ip_address",
            "attempted_at",
        ),
        Index("ix_login_attempts_ip_time", "ip_address", "attempted_at"),
    )
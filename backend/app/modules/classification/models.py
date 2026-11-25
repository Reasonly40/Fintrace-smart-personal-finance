import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.session import Base
from app.db.sql import sql_in
from app.modules.classification.enums import CategoryType


class Category(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Kategori global (user_id NULL) atau personal (user_id pemilik)."""

    __tablename__ = "categories"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    # Dikunci NULL oleh CHECK selama MVP datar (keputusan 4)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # Kolom turunan untuk keunikan tanpa membedakan huruf besar kecil
    name_key: Mapped[str] = mapped_column(
        String(80), Computed("lower(name)", persisted=True)
    )
    category_type: Mapped[str] = mapped_column(String(10), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(32), nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    __table_args__ = (
        CheckConstraint(
            sql_in("category_type", CategoryType), name="type_valid"
        ),
        CheckConstraint(
            "length(btrim(name)) > 0 AND name = btrim(name)",
            name="name_trimmed",
        ),
        CheckConstraint(
            "color IS NULL OR color ~ '^#[0-9A-Fa-f]{6}$'", name="color_hex"
        ),
        CheckConstraint("parent_id IS NULL", name="flat_in_mvp"),
        # Satu nama per tipe di antara kategori global
        Index(
            "uq_categories_global_name",
            "category_type",
            "name_key",
            unique=True,
            postgresql_where=text("user_id IS NULL"),
        ),
        # Satu nama per tipe untuk tiap pemilik
        Index(
            "uq_categories_personal_name",
            "user_id",
            "category_type",
            "name_key",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index("ix_categories_user_id", "user_id"),
    )
    @property
    def is_global(self) -> bool:
        return self.user_id is None
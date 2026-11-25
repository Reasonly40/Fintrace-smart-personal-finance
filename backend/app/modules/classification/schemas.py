import re
import uuid
from datetime import datetime
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.modules.classification.enums import CategoryType

# Nama ikon dalam huruf kecil, misalnya "utensils" atau "shopping-bag"
ICON_PATTERN = r"^[a-z0-9][a-z0-9-]{0,31}$"
COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _clean_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Nama tidak boleh kosong.")
    return value


def _clean_color(value: str | None) -> str | None:
    if value is None:
        return None
    if not COLOR_PATTERN.fullmatch(value):
        raise ValueError("Warna harus berformat #RRGGBB.")
    return value.upper()


class CategoryCreate(BaseModel):
    # Field asing (user_id, parent_id, is_active, ...) ditolak, bukan diabaikan
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    category_type: CategoryType
    icon: str | None = Field(default=None, pattern=ICON_PATTERN)
    color: str | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return _clean_name(value)

    @field_validator("color")
    @classmethod
    def clean_color(cls, value: str | None) -> str | None:
        return _clean_color(value)


class CategoryUpdate(BaseModel):
    """PATCH: hanya field yang dikirim yang berubah. Mengirim null pada
    icon atau color menghapus nilainya; name tidak boleh null."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    icon: str | None = Field(default=None, pattern=ICON_PATTERN)
    color: str | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Nama tidak boleh dikosongkan.")
        return _clean_name(value)

    @field_validator("color")
    @classmethod
    def clean_color(cls, value: str | None) -> str | None:
        return _clean_color(value)

    @model_validator(mode="after")
    def require_a_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Minimal satu field harus diisi.")
        return self


class CategoryResponse(BaseModel):
    """Yang boleh keluar ke klien. user_id dan parent_id sengaja tidak ada."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category_type: CategoryType
    icon: str | None
    color: str | None
    is_active: bool
    is_global: bool
    created_at: datetime
    updated_at: datetime
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

from app.modules.wallet.enums import WalletType


def _clean_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Nama tidak boleh kosong.")
    return value


class WalletCreate(BaseModel):
    # Field tak dikenal (user_id, currency, ...) ditolak, bukan diabaikan
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    wallet_type: WalletType

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return _clean_name(value)


class WalletUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    wallet_type: WalletType | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        return None if value is None else _clean_name(value)

    @model_validator(mode="after")
    def require_a_change(self) -> Self:
        if self.name is None and self.wallet_type is None:
            raise ValueError("Minimal satu field harus diisi.")
        return self


class WalletResponse(BaseModel):
    """Yang boleh keluar ke klien. user_id sengaja tidak ada."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    wallet_type: WalletType
    currency: str
    is_active: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
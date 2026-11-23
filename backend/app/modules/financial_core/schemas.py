import uuid
from datetime import datetime

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from app.core.money import Rupiah
from app.modules.financial_core.enums import (
    EntryType,
    TransactionStatus,
    TransactionType,
)


class TransactionCreate(BaseModel):
    # Field asing (user_id, status, currency, ...) ditolak, bukan diabaikan
    model_config = ConfigDict(extra="forbid")

    transaction_type: TransactionType
    wallet_id: uuid.UUID
    amount: Rupiah
    occurred_at: AwareDatetime
    description: str | None = Field(default=None, max_length=500)

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class TransactionResponse(BaseModel):
    """Yang boleh keluar ke klien. user_id sengaja tidak ada."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transaction_type: TransactionType
    status: TransactionStatus
    amount: int
    currency: str
    wallet_id: uuid.UUID | None
    from_wallet_id: uuid.UUID | None
    to_wallet_id: uuid.UUID | None
    description: str | None
    occurred_at: datetime
    posted_at: datetime | None
    reversal_of_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class EntryResponse(BaseModel):
    account_id: uuid.UUID
    account_code: str
    account_name: str
    entry_type: EntryType
    amount: int


class TransactionDetailResponse(TransactionResponse):
    entries: list[EntryResponse]
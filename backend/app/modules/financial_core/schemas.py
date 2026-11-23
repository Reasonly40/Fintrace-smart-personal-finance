import uuid
from datetime import datetime
from typing import Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
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
    # INCOME, EXPENSE, OPENING_BALANCE memakai wallet_id;
    # TRANSFER memakai from_wallet_id dan to_wallet_id (bagian 8.6)
    wallet_id: uuid.UUID | None = None
    from_wallet_id: uuid.UUID | None = None
    to_wallet_id: uuid.UUID | None = None
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

    @model_validator(mode="after")
    def check_wallet_fields(self) -> Self:
        if self.transaction_type == TransactionType.TRANSFER:
            if (
                self.wallet_id is not None
                or self.from_wallet_id is None
                or self.to_wallet_id is None
            ):
                raise ValueError(
                    "Transfer memerlukan from_wallet_id dan to_wallet_id, "
                    "tanpa wallet_id."
                )
            if self.from_wallet_id == self.to_wallet_id:
                raise ValueError("Wallet asal dan tujuan tidak boleh sama.")
        elif (
            self.wallet_id is None
            or self.from_wallet_id is not None
            or self.to_wallet_id is not None
        ):
            raise ValueError(
                "Tipe ini memerlukan wallet_id, tanpa from_wallet_id "
                "atau to_wallet_id."
            )
        return self


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
    reversed_by_id: uuid.UUID | None = None


class ReversalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Alasan tidak boleh kosong.")
        return value


class ReversalResponse(BaseModel):
    original: TransactionDetailResponse
    reversal: TransactionDetailResponse
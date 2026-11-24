import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.timezones import DEFAULT_TIMEZONE, is_valid_timezone


def _check_timezone(value: str) -> str:
    if not is_valid_timezone(value):
        raise ValueError(
            "Zona waktu tidak dikenal. Gunakan nama IANA, "
            "misalnya Asia/Makassar."
        )
    return value

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)

    @field_validator("full_name")
    @classmethod
    def strip_full_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Nama tidak boleh kosong.")
        return value
    
    timezone: str = DEFAULT_TIMEZONE

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, value: str) -> str:
        return _check_timezone(value)
    

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

class UserResponse(BaseModel):
    """Yang boleh keluar ke klien. password_hash sengaja tidak ada."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    timezone: str
    created_at: datetime

class SessionResponse(BaseModel):
    """Info sesi untuk pemiliknya. token_hash sengaja tidak ada."""

    id: uuid.UUID
    created_at: datetime
    expires_at: datetime
    is_current: bool

class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, value: str) -> str:
        return _check_timezone(value)
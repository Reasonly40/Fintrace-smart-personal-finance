import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditLogResponse(BaseModel):
    """Aktivitas milik pengguna sendiri. user_id sengaja tidak ada."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: str
    resource_type: str | None
    resource_id: uuid.UUID | None
    metadata: dict[str, Any] = Field(validation_alias="event_metadata")
    ip_address: str | None
    created_at: datetime
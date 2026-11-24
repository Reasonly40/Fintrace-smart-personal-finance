import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import DbSession
from app.core.pagination import Page
from app.modules.identity.dependencies import CurrentUser
from app.modules.operations import audit
from app.modules.operations.schemas import AuditLogResponse

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=Page[AuditLogResponse])
def list_audit_logs(
    db: DbSession,
    user: CurrentUser,
    action: Annotated[str | None, Query(max_length=64)] = None,
    resource_type: Annotated[str | None, Query(max_length=32)] = None,
    resource_id: uuid.UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[AuditLogResponse]:
    logs, total = audit.list_logs(
        db,
        user_id=user.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        page=page,
        limit=limit,
    )
    return Page[AuditLogResponse](
        items=[AuditLogResponse.model_validate(log) for log in logs],
        page=page,
        limit=limit,
        total=total,
    )
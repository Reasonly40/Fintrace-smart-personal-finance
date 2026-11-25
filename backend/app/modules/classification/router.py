import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from app.core.deps import DbSession
from app.core.http import client_ip
from app.core.pagination import Page
from app.modules.classification import service
from app.modules.classification.enums import CategoryType
from app.modules.classification.schemas import (
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
)
from app.modules.classification.service import (
    ScopeFilter,
    SortField,
    SortOrder,
    StatusFilter,
)
from app.modules.identity.dependencies import CurrentUser

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=Page[CategoryResponse])
def list_categories(
    db: DbSession,
    user: CurrentUser,
    category_type: Annotated[CategoryType | None, Query(alias="type")] = None,
    scope: ScopeFilter = "all",
    status_filter: Annotated[StatusFilter, Query(alias="status")] = "active",
    q: Annotated[str | None, Query(max_length=80)] = None,
    sort: SortField = "name",
    order: SortOrder = "asc",
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[CategoryResponse]:
    categories, total = service.list_categories(
        db,
        user_id=user.id,
        category_type=category_type,
        scope=scope,
        status=status_filter,
        search=q,
        sort=sort,
        order=order,
        page=page,
        limit=limit,
    )
    return Page[CategoryResponse](
        items=[CategoryResponse.model_validate(c) for c in categories],
        page=page,
        limit=limit,
        total=total,
    )


@router.post(
    "", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED
)
def create_category(
    payload: CategoryCreate,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> CategoryResponse:
    category = service.create_category(
        db,
        user_id=user.id,
        name=payload.name,
        category_type=payload.category_type,
        icon=payload.icon,
        color=payload.color,
        ip_address=client_ip(request),
    )
    return CategoryResponse.model_validate(category)


@router.get("/{category_id}", response_model=CategoryResponse)
def get_category(
    category_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> CategoryResponse:
    category = service.get_category(
        db, user_id=user.id, category_id=category_id
    )
    return CategoryResponse.model_validate(category)


@router.patch("/{category_id}", response_model=CategoryResponse)
def update_category(
    category_id: uuid.UUID,
    payload: CategoryUpdate,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> CategoryResponse:
    category = service.update_category(
        db,
        user_id=user.id,
        category_id=category_id,
        changes=payload.model_dump(exclude_unset=True),
        ip_address=client_ip(request),
    )
    return CategoryResponse.model_validate(category)


@router.post("/{category_id}/archive", response_model=CategoryResponse)
def archive_category(
    category_id: uuid.UUID,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> CategoryResponse:
    category = service.archive_category(
        db,
        user_id=user.id,
        category_id=category_id,
        ip_address=client_ip(request),
    )
    return CategoryResponse.model_validate(category)


@router.post("/{category_id}/unarchive", response_model=CategoryResponse)
def unarchive_category(
    category_id: uuid.UUID,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> CategoryResponse:
    category = service.unarchive_category(
        db,
        user_id=user.id,
        category_id=category_id,
        ip_address=client_ip(request),
    )
    return CategoryResponse.model_validate(category)
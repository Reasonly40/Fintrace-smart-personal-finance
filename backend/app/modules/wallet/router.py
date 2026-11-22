import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.deps import DbSession
from app.core.pagination import Page
from app.modules.identity.dependencies import CurrentUser
from app.modules.wallet import service
from app.modules.wallet.enums import WalletType
from app.modules.wallet.models import Wallet
from app.modules.wallet.schemas import (
    WalletCreate,
    WalletResponse,
    WalletUpdate,
)
from app.modules.wallet.service import SortField, SortOrder, StatusFilter

router = APIRouter(prefix="/wallets", tags=["wallets"])


@router.post(
    "", response_model=WalletResponse, status_code=status.HTTP_201_CREATED
)
def create_wallet(
    payload: WalletCreate, db: DbSession, user: CurrentUser
) -> Wallet:
    return service.create_wallet(
        db,
        user_id=user.id,
        name=payload.name,
        wallet_type=payload.wallet_type,
    )


@router.get("", response_model=Page[WalletResponse])
def list_wallets(
    db: DbSession,
    user: CurrentUser,
    status_filter: Annotated[StatusFilter, Query(alias="status")] = "active",
    wallet_type: WalletType | None = None,
    sort: SortField = "created_at",
    order: SortOrder = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[WalletResponse]:
    wallets, total = service.list_wallets(
        db,
        user_id=user.id,
        status=status_filter,
        wallet_type=wallet_type,
        sort=sort,
        order=order,
        page=page,
        limit=limit,
    )
    return Page[WalletResponse](
        items=[WalletResponse.model_validate(w) for w in wallets],
        page=page,
        limit=limit,
        total=total,
    )


@router.get("/{wallet_id}", response_model=WalletResponse)
def get_wallet(
    wallet_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> Wallet:
    return service.get_wallet(db, user_id=user.id, wallet_id=wallet_id)


@router.patch("/{wallet_id}", response_model=WalletResponse)
def update_wallet(
    wallet_id: uuid.UUID,
    payload: WalletUpdate,
    db: DbSession,
    user: CurrentUser,
) -> Wallet:
    return service.update_wallet(
        db,
        user_id=user.id,
        wallet_id=wallet_id,
        name=payload.name,
        wallet_type=payload.wallet_type,
    )


@router.post("/{wallet_id}/archive", response_model=WalletResponse)
def archive_wallet(
    wallet_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> Wallet:
    return service.archive_wallet(db, user_id=user.id, wallet_id=wallet_id)
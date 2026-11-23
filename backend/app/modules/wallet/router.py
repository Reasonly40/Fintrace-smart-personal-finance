import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy.orm import Session

from app.core.deps import DbSession
from app.core.pagination import Page
from app.modules.financial_core.balance import wallet_balance, wallet_balances
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


def to_response(wallet: Wallet, balance: int) -> WalletResponse:
    return WalletResponse(
        id=wallet.id,
        name=wallet.name,
        wallet_type=wallet.wallet_type,
        currency=wallet.currency,
        is_active=wallet.is_active,
        archived_at=wallet.archived_at,
        created_at=wallet.created_at,
        updated_at=wallet.updated_at,
        balance=balance,
    )


def respond(db: Session, wallet: Wallet) -> WalletResponse:
    balance = wallet_balance(db, user_id=wallet.user_id, wallet_id=wallet.id)
    return to_response(wallet, balance)


@router.post(
    "", response_model=WalletResponse, status_code=status.HTTP_201_CREATED
)
def create_wallet(
    payload: WalletCreate, db: DbSession, user: CurrentUser
) -> WalletResponse:
    wallet = service.create_wallet(
        db,
        user_id=user.id,
        name=payload.name,
        wallet_type=payload.wallet_type,
    )
    return respond(db, wallet)


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
    balances = wallet_balances(
        db, user_id=user.id, wallet_ids=[w.id for w in wallets]
    )
    return Page[WalletResponse](
        items=[to_response(w, balances[w.id]) for w in wallets],
        page=page,
        limit=limit,
        total=total,
    )


@router.get("/{wallet_id}", response_model=WalletResponse)
def get_wallet(
    wallet_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> WalletResponse:
    wallet = service.get_wallet(db, user_id=user.id, wallet_id=wallet_id)
    return respond(db, wallet)


@router.patch("/{wallet_id}", response_model=WalletResponse)
def update_wallet(
    wallet_id: uuid.UUID,
    payload: WalletUpdate,
    db: DbSession,
    user: CurrentUser,
) -> WalletResponse:
    wallet = service.update_wallet(
        db,
        user_id=user.id,
        wallet_id=wallet_id,
        name=payload.name,
        wallet_type=payload.wallet_type,
    )
    return respond(db, wallet)


@router.post("/{wallet_id}/archive", response_model=WalletResponse)
def archive_wallet(
    wallet_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> WalletResponse:
    wallet = service.archive_wallet(
        db, user_id=user.id, wallet_id=wallet_id
    )
    return respond(db, wallet)
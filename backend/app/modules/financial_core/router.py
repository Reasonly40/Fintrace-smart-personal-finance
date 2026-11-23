import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Header, Query, Response, status
from sqlalchemy.orm import Session

from app.core.deps import DbSession
from app.core.pagination import Page
from app.modules.financial_core import service
from app.modules.financial_core.enums import (
    TransactionStatus,
    TransactionType,
)
from app.modules.financial_core.models import Transaction
from app.modules.financial_core.schemas import (
    EntryResponse,
    TransactionCreate,
    TransactionDetailResponse,
    TransactionResponse,
)
from app.modules.financial_core.service import TxSortField, TxSortOrder
from app.modules.identity.dependencies import CurrentUser

router = APIRouter(prefix="/transactions", tags=["transactions"])

KEY_PATTERN = r"^[A-Za-z0-9._:-]+$"
IdempotencyKey = Annotated[
    str, Header(min_length=8, max_length=128, pattern=KEY_PATTERN)
]
OptionalIdempotencyKey = Annotated[
    str | None, Header(min_length=8, max_length=128, pattern=KEY_PATTERN)
]


def detail_response(
    db: Session, transaction: Transaction
) -> TransactionDetailResponse:
    rows = service.get_transaction_entries(
        db, user_id=transaction.user_id, transaction_id=transaction.id
    )
    base = TransactionResponse.model_validate(transaction).model_dump()
    return TransactionDetailResponse(
        **base,
        entries=[
            EntryResponse(
                account_id=account.id,
                account_code=account.account_code,
                account_name=account.account_name,
                entry_type=entry.entry_type,
                amount=entry.amount,
            )
            for entry, account in rows
        ],
    )


@router.post(
    "",
    response_model=TransactionDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_transaction(
    payload: TransactionCreate,
    response: Response,
    db: DbSession,
    user: CurrentUser,
    idempotency_key: OptionalIdempotencyKey = None,
) -> TransactionDetailResponse:
    result = service.create_draft_with_idempotency(
        db,
        user_id=user.id,
        idempotency_key=idempotency_key,
        transaction_type=payload.transaction_type,
        amount=payload.amount,
        wallet_id=payload.wallet_id,
        occurred_at=payload.occurred_at,
        description=payload.description,
    )
    if result.replayed:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replay"] = "true"
    transaction = service.get_transaction(
        db, user_id=user.id, transaction_id=result.transaction_id
    )
    return detail_response(db, transaction)


@router.get("", response_model=Page[TransactionResponse])
def list_transactions(
    db: DbSession,
    user: CurrentUser,
    wallet_id: uuid.UUID | None = None,
    transaction_type: TransactionType | None = None,
    status_filter: Annotated[
        TransactionStatus | None, Query(alias="status")
    ] = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    sort: TxSortField = "occurred_at",
    order: TxSortOrder = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[TransactionResponse]:
    transactions, total = service.list_transactions(
        db,
        user_id=user.id,
        wallet_id=wallet_id,
        transaction_type=transaction_type,
        status=status_filter,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        search=q,
        sort=sort,
        order=order,
        page=page,
        limit=limit,
    )
    return Page[TransactionResponse](
        items=[TransactionResponse.model_validate(t) for t in transactions],
        page=page,
        limit=limit,
        total=total,
    )


@router.get("/{transaction_id}", response_model=TransactionDetailResponse)
def get_transaction(
    transaction_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> TransactionDetailResponse:
    transaction = service.get_transaction(
        db, user_id=user.id, transaction_id=transaction_id
    )
    return detail_response(db, transaction)


@router.post("/{transaction_id}/post", response_model=TransactionDetailResponse)
def post_transaction(
    transaction_id: uuid.UUID,
    response: Response,
    db: DbSession,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
) -> TransactionDetailResponse:
    result = service.post_with_idempotency(
        db,
        user_id=user.id,
        transaction_id=transaction_id,
        idempotency_key=idempotency_key,
    )
    if result.replayed:
        response.headers["Idempotent-Replay"] = "true"
    transaction = service.get_transaction(
        db, user_id=user.id, transaction_id=result.transaction_id
    )
    return detail_response(db, transaction)
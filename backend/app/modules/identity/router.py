from fastapi import APIRouter, status

from app.core.deps import DbSession
from app.modules.identity import service
from app.modules.identity.models import User
from app.modules.identity.schemas import RegisterRequest, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(payload: RegisterRequest, db: DbSession) -> User:
    return service.register_user(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
    )
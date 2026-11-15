from fastapi import APIRouter, Request, Response, status

from app.core.config import settings
from app.core.deps import DbSession
from app.modules.identity import service
from app.modules.identity.dependencies import CurrentUser
from app.modules.identity.models import User
from app.modules.identity.schemas import (
    LoginRequest,
    RegisterRequest,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_days * 24 * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


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


@router.post("/login", response_model=UserResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> User:
    user = service.authenticate(
        db, email=payload.email, password=payload.password
    )
    # Rotasi: cabut sesi lama bila klien masih membawa cookie
    old_token = request.cookies.get(settings.session_cookie_name)
    if old_token:
        service.revoke_session(db, old_token)

    token = service.create_session(db, user)
    set_session_cookie(response, token)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, db: DbSession) -> Response:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        service.revoke_session(db, token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser) -> User:
    return user
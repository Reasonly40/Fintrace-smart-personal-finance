import uuid

from fastapi import APIRouter, Request, Response, status

from app.core.config import settings
from app.core.csrf import make_csrf_token
from app.core.deps import DbSession
from app.modules.identity import service
from app.modules.identity.dependencies import CurrentUser
from app.modules.identity.models import User
from app.modules.identity.schemas import (
    LoginRequest,
    RegisterRequest,
    SessionResponse,
    UpdateProfileRequest,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def set_auth_cookies(response: Response, session_token: str) -> None:
    max_age = settings.session_ttl_days * 24 * 3600
    # Cookie sesi: tidak terbaca JavaScript
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    # Cookie CSRF: sengaja terbaca JavaScript agar bisa dikirim sebagai header
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=make_csrf_token(session_token),
        max_age=max_age,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    response.delete_cookie(
        key=settings.csrf_cookie_name,
        path="/",
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
        timezone=payload.timezone
    )


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=UserResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> User:
    user = service.login(
        db,
        email=payload.email,
        password=payload.password,
        ip=client_ip(request),
    )
    # Rotasi: cabut sesi lama bila klien masih membawa cookie
    old_token = request.cookies.get(settings.session_cookie_name)
    if old_token:
        service.revoke_session(db, old_token)

    token = service.create_session(db, user)
    set_auth_cookies(response, token)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, db: DbSession) -> Response:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        service.revoke_session(db, token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookies(response)
    return response


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser) -> User:
    return user

@router.get("/sessions", response_model=list[SessionResponse])
def list_sessions(
    request: Request, db: DbSession, user: CurrentUser
) -> list[dict[str, object]]:
    token = request.cookies.get(settings.session_cookie_name)
    return service.list_active_sessions(db, user, token)


@router.delete(
    "/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_session(
    session_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> Response:
    service.revoke_user_session(db, user, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.patch("/me", response_model=UserResponse)
def update_me(
    payload: UpdateProfileRequest, db: DbSession, user: CurrentUser
) -> User:
    return service.update_timezone(db, user=user, timezone=payload.timezone)
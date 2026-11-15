from typing import Annotated

from fastapi import Cookie, Depends

from app.core.config import settings
from app.core.deps import DbSession
from app.modules.identity import service
from app.modules.identity.models import User


def get_current_user(
    db: DbSession,
    session_token: Annotated[
        str | None, Cookie(alias=settings.session_cookie_name)
    ] = None,
) -> User:
    if not session_token:
        raise service.NotAuthenticatedError()
    user = service.get_user_by_session_token(db, session_token)
    if user is None:
        raise service.NotAuthenticatedError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
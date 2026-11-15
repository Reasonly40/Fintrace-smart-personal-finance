import hashlib
import hmac
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Header, Request

from app.core.config import settings
from app.core.errors import ForbiddenError

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Login dan registrasi belum punya sesi, jadi tidak ada token yang bisa
# dicocokkan. Keduanya tetap dijaga oleh pengecekan Origin/Referer.
TOKEN_EXEMPT_PATHS = {"/api/v1/auth/login", "/api/v1/auth/register"}


class CSRFError(ForbiddenError):
    code = "csrf_failed"
    message = "Permintaan ditolak oleh proteksi CSRF."


def make_csrf_token(session_token: str) -> str:
    """Token CSRF terikat ke sesi: HMAC(kunci server, token sesi)."""
    digest = hmac.new(
        settings.secret_key.encode(),
        f"csrf:{session_token}".encode(),
        hashlib.sha256,
    )
    return digest.hexdigest()


def _origin_of(url: str) -> str | None:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def csrf_protect(
    request: Request,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> None:
    if request.method in SAFE_METHODS:
        return

    # Lapis 1: asal request. Origin diutamakan, Referer sebagai cadangan.
    source = request.headers.get("origin") or request.headers.get("referer")
    if source is not None:
        if _origin_of(source) not in settings.allowed_origins_list:
            raise CSRFError()

    if request.url.path in TOKEN_EXEMPT_PATHS:
        return

    # Lapis 2: token, hanya relevan bila request membawa cookie sesi.
    session_token = request.cookies.get(settings.session_cookie_name)
    if not session_token:
        return
    expected = make_csrf_token(session_token)
    if not x_csrf_token or not hmac.compare_digest(
        x_csrf_token.encode(), expected.encode()
    ):
        raise CSRFError()
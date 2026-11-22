import hashlib
import hmac
import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import TooManyRequestsError
from app.modules.identity.models import LoginAttempt


class LoginThrottledError(TooManyRequestsError):
    code = "too_many_login_attempts"
    message = "Terlalu banyak percobaan login. Coba lagi nanti."


def email_fingerprint(email: str) -> str:
    """HMAC email ternormalisasi; email asli tidak disimpan di tabel."""
    return hmac.new(
        settings.secret_key.encode(),
        email.strip().lower().encode(),
        hashlib.sha256,
    ).hexdigest()


def _window() -> timedelta:
    return timedelta(minutes=settings.login_window_minutes)


def _retry_after(
    db: Session, conditions: list[ColumnElement[bool]], limit: int
) -> int | None:
    """Detik sampai boleh mencoba lagi, atau None bila belum mencapai batas."""
    now = datetime.now(UTC)
    times = (
        db.execute(
            select(LoginAttempt.attempted_at)
            .where(*conditions, LoginAttempt.attempted_at > now - _window())
            .order_by(LoginAttempt.attempted_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    if len(times) < limit:
        return None
    # Percobaan ke-`limit` dari yang terbaru: begitu ia keluar dari jendela,
    # jumlah kegagalan turun di bawah batas.
    unlock_at = times[-1] + _window()
    return max(1, math.ceil((unlock_at - now).total_seconds()))


def ensure_login_allowed(db: Session, *, email: str, ip: str) -> None:
    fingerprint = email_fingerprint(email)
    waits = [
        _retry_after(
            db,
            [
                LoginAttempt.email_hash == fingerprint,
                LoginAttempt.ip_address == ip,
            ],
            settings.login_max_failures_per_account_ip,
        ),
        _retry_after(
            db,
            [LoginAttempt.ip_address == ip],
            settings.login_max_failures_per_ip,
        ),
    ]
    blocked = [w for w in waits if w is not None]
    if blocked:
        raise LoginThrottledError(retry_after=max(blocked))


def record_failed_login(db: Session, *, email: str, ip: str) -> None:
    db.add(LoginAttempt(email_hash=email_fingerprint(email), ip_address=ip))
    db.commit()


def clear_failed_logins(db: Session, *, email: str, ip: str) -> None:
    db.execute(
        delete(LoginAttempt).where(
            LoginAttempt.email_hash == email_fingerprint(email),
            LoginAttempt.ip_address == ip,
        )
    )
    db.commit()


def purge_old_attempts(db: Session) -> int:
    """Hapus catatan di luar jendela waktu. Dijadwalkan di Fase 7."""
    result = db.execute(
        delete(LoginAttempt).where(
            LoginAttempt.attempted_at < datetime.now(UTC) - _window()
        )
    )
    db.commit()
    return result.rowcount
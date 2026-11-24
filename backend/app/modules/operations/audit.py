import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.operations.models import AuditLog

# Bagian 10.3: jangan menulis kredensial atau data finansial berlebihan.
# Pemeriksaan ini dangkal (hanya kunci tingkat atas) dan berfungsi sebagai
# pagar pengaman, bukan pengganti kehati-hatian penulis kode.
FORBIDDEN_METADATA_KEYS = frozenset(
    {"password", "password_hash", "token", "session_token", "secret", "amount"}
)


class AuditAction(StrEnum):
    USER_REGISTERED = "auth.registered"
    LOGIN_SUCCEEDED = "auth.login_succeeded"
    LOGIN_FAILED = "auth.login_failed"
    LOGOUT = "auth.logout"
    SESSION_REVOKED = "auth.session_revoked"
    TIMEZONE_CHANGED = "user.timezone_changed"
    WALLET_CREATED = "wallet.created"
    WALLET_UPDATED = "wallet.updated"
    WALLET_ARCHIVED = "wallet.archived"
    TRANSACTION_POSTED = "transaction.posted"
    TRANSACTION_REVERSED = "transaction.reversed"


def record(
    db: Session,
    *,
    user_id: uuid.UUID | None,
    action: AuditAction,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """Catat satu kejadian di dalam transaksi pemanggil. Tanpa commit:
    audit commit atau batal bersama aksinya (bagian 18.3)."""
    data = metadata or {}
    forbidden = FORBIDDEN_METADATA_KEYS & {str(key).lower() for key in data}
    if forbidden:
        raise ValueError(
            f"Metadata audit tidak boleh memuat: {sorted(forbidden)}"
        )
    entry = AuditLog(
        user_id=user_id,
        action=action.value,
        resource_type=resource_type,
        resource_id=resource_id,
        event_metadata=data,
        ip_address=ip_address,
    )
    db.add(entry)
    db.flush()
    return entry

def list_logs(
    db: Session,
    *,
    user_id: uuid.UUID,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[AuditLog], int]:
    """Audit milik user. Kejadian tanpa pengguna (user_id NULL) tidak
    pernah muncul di sini."""
    conditions = [AuditLog.user_id == user_id]
    if action:
        conditions.append(AuditLog.action == action)
    if resource_type:
        conditions.append(AuditLog.resource_type == resource_type)
    if resource_id is not None:
        conditions.append(AuditLog.resource_id == resource_id)

    total = db.execute(
        select(func.count()).select_from(AuditLog).where(*conditions)
    ).scalar_one()
    rows = (
        db.execute(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc(), AuditLog.id)
            .limit(limit)
            .offset((page - 1) * limit)
        )
        .scalars()
        .all()
    )
    return list(rows), total
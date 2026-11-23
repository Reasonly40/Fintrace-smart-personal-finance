import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.operations.enums import IdempotencyStatus
from app.modules.operations.errors import (
    IdempotencyInProgressError,
    IdempotencyKeyReusedError,
)
from app.modules.operations.models import IdempotencyRecord

UNIQUE_KEY_CONSTRAINT = "uq_idempotency_records_user_id_idempotency_key"


@dataclass(frozen=True)
class IdempotencyOutcome:
    record: IdempotencyRecord
    replayed: bool

    @property
    def response(self) -> dict[str, Any] | None:
        """Jawaban tersimpan, hanya ada bila ini pemutaran ulang."""
        return self.record.response_data if self.replayed else None


def request_fingerprint(operation: str, payload: Mapping[str, Any]) -> str:
    """Hash stabil dari nama operasi dan isi permintaan."""
    canonical = json.dumps(
        {"operation": operation, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def begin(
    db: Session,
    *,
    user_id: uuid.UUID,
    key: str,
    request_hash: str,
    allow_retry: bool = True,
) -> IdempotencyOutcome:
    """Klaim key di dalam transaksi pemanggil. Tidak melakukan commit.

    Key baru: record PROCESSING dibuat. Key yang sudah selesai dengan
    payload sama: kembalikan jawaban tersimpan. Bila ada transaksi lain
    yang sedang memegang key yang sama, INSERT menunggu sampai transaksi
    itu selesai, sehingga duplikat tidak pernah berjalan paralel.
    """
    now = datetime.now(UTC)
    inserted_id = db.execute(
        pg_insert(IdempotencyRecord)
        .values(
            user_id=user_id,
            idempotency_key=key,
            request_hash=request_hash,
            status=IdempotencyStatus.PROCESSING.value,
            expires_at=now + timedelta(hours=settings.idempotency_ttl_hours),
        )
        .on_conflict_do_nothing(constraint=UNIQUE_KEY_CONSTRAINT)
        .returning(IdempotencyRecord.id)
    ).scalar_one_or_none()

    if inserted_id is not None:
        record = db.get(IdempotencyRecord, inserted_id)
        return IdempotencyOutcome(record=record, replayed=False)

    existing = db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.idempotency_key == key,
        )
    ).scalar_one()

    if existing.expires_at <= now and allow_retry:
        db.delete(existing)
        db.flush()
        return begin(
            db,
            user_id=user_id,
            key=key,
            request_hash=request_hash,
            allow_retry=False,
        )
    if existing.request_hash != request_hash:
        raise IdempotencyKeyReusedError()
    if existing.status != IdempotencyStatus.COMPLETED.value:
        raise IdempotencyInProgressError()
    return IdempotencyOutcome(record=existing, replayed=True)


def complete(
    db: Session, record: IdempotencyRecord, response: dict[str, Any]
) -> None:
    """Simpan jawaban. Dipanggil sebelum commit transaksi bisnis."""
    record.status = IdempotencyStatus.COMPLETED.value
    record.response_data = response
    db.flush()
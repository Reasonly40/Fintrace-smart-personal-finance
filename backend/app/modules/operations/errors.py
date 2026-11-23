from app.core.errors import ConflictError


class IdempotencyKeyReusedError(ConflictError):
    code = "idempotency_key_reused"
    message = "Idempotency-Key ini sudah dipakai untuk permintaan yang berbeda."


class IdempotencyInProgressError(ConflictError):
    code = "idempotency_in_progress"
    message = "Permintaan dengan Idempotency-Key ini masih diproses."
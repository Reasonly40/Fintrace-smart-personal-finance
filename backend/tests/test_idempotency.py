from datetime import UTC, datetime, timedelta

import pytest

from app.modules.operations import service as idem
from app.modules.operations.errors import (
    IdempotencyInProgressError,
    IdempotencyKeyReusedError,
)
from app.modules.operations.models import IdempotencyRecord
from tests.ledger_helpers import expect_rejected, make_user

HASH_A = "a" * 64
HASH_B = "b" * 64


def build_record(user_id, **overrides):
    values = {
        "user_id": user_id,
        "idempotency_key": "kunci-1",
        "request_hash": HASH_A,
        "status": "PROCESSING",
        "expires_at": datetime.now(UTC) + timedelta(hours=24),
    }
    values.update(overrides)
    return IdempotencyRecord(**values)


def begin(db, user, key="k1", request_hash=HASH_A):
    return idem.begin(db, user_id=user.id, key=key, request_hash=request_hash)


# ---------- constraint tabel ----------


def test_record_gets_uuid_and_defaults(db_session):
    user = make_user(db_session)
    record = build_record(user.id)
    db_session.add(record)
    db_session.flush()
    db_session.refresh(record)

    assert record.id is not None
    assert record.response_data is None
    assert record.created_at.tzinfo is not None


def test_key_is_unique_per_user(db_session):
    user = make_user(db_session)
    db_session.add(build_record(user.id))
    db_session.flush()

    expect_rejected(db_session, build_record(user.id))


def test_same_key_is_allowed_for_different_users(db_session):
    first = make_user(db_session, "satu@example.com")
    second = make_user(db_session, "dua@example.com")

    db_session.add_all([build_record(first.id), build_record(second.id)])
    db_session.flush()


def test_status_must_be_known(db_session):
    user = make_user(db_session)

    expect_rejected(db_session, build_record(user.id, status="DONE"))


@pytest.mark.parametrize(
    "extra",
    [
        {"status": "PROCESSING", "response_data": {"a": 1}},
        {"status": "COMPLETED"},
    ],
)
def test_response_must_match_status(db_session, extra):
    user = make_user(db_session)

    expect_rejected(db_session, build_record(user.id, **extra))


def test_blank_key_is_rejected(db_session):
    user = make_user(db_session)

    expect_rejected(db_session, build_record(user.id, idempotency_key="   "))


# ---------- service ----------


def test_begin_stores_a_processing_record(db_session):
    user = make_user(db_session)

    outcome = begin(db_session, user)

    assert outcome.replayed is False
    assert outcome.record.status == "PROCESSING"
    assert outcome.response is None


def test_complete_stores_the_response(db_session):
    user = make_user(db_session)
    outcome = begin(db_session, user)

    idem.complete(db_session, outcome.record, {"transaction_id": "abc"})

    assert outcome.record.status == "COMPLETED"
    assert outcome.record.response_data == {"transaction_id": "abc"}


def test_same_key_and_payload_replays_the_stored_response(db_session):
    user = make_user(db_session)
    first = begin(db_session, user)
    idem.complete(db_session, first.record, {"transaction_id": "abc"})

    second = begin(db_session, user)

    assert second.replayed is True
    assert second.response == {"transaction_id": "abc"}
    assert second.record.id == first.record.id


def test_same_key_with_a_different_payload_is_a_conflict(db_session):
    user = make_user(db_session)
    first = begin(db_session, user)
    idem.complete(db_session, first.record, {"transaction_id": "abc"})

    with pytest.raises(IdempotencyKeyReusedError):
        begin(db_session, user, request_hash=HASH_B)


def test_unfinished_request_is_reported_as_in_progress(db_session):
    user = make_user(db_session)
    begin(db_session, user)

    with pytest.raises(IdempotencyInProgressError):
        begin(db_session, user)


def test_expired_record_is_replaced(db_session):
    user = make_user(db_session)
    first = begin(db_session, user)
    old_id = first.record.id
    first.record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()

    second = begin(db_session, user, request_hash=HASH_B)

    assert second.replayed is False
    assert second.record.id != old_id
    assert second.record.request_hash == HASH_B


def test_users_do_not_share_keys(db_session):
    first = make_user(db_session, "satu@example.com")
    second = make_user(db_session, "dua@example.com")

    assert begin(db_session, first).replayed is False
    assert begin(db_session, second).replayed is False


def test_fingerprint_ignores_key_order():
    one = idem.request_fingerprint("op", {"a": 1, "b": 2})
    two = idem.request_fingerprint("op", {"b": 2, "a": 1})

    assert one == two


def test_fingerprint_differs_by_operation():
    payload = {"transaction_id": "1"}

    assert idem.request_fingerprint("post", payload) != idem.request_fingerprint(
        "reverse", payload
    )


def test_fingerprint_differs_by_payload():
    assert idem.request_fingerprint("op", {"id": "1"}) != idem.request_fingerprint(
        "op", {"id": "2"}
    )
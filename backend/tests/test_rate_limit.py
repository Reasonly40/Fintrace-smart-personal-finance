from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.core.config import settings
from app.modules.identity import rate_limit
from app.modules.identity.models import LoginAttempt
from app.modules.identity.rate_limit import LoginThrottledError

EMAIL = "budi@example.com"
IP = "10.0.0.1"
OTHER_IP = "10.0.0.2"


def fail(db, count, *, email=EMAIL, ip=IP):
    for _ in range(count):
        rate_limit.record_failed_login(db, email=email, ip=ip)


def shift_back(db, minutes):
    db.execute(
        update(LoginAttempt).values(
            attempted_at=LoginAttempt.attempted_at - timedelta(minutes=minutes)
        )
    )


def count_rows(db):
    return db.execute(select(func.count()).select_from(LoginAttempt)).scalar_one()


def test_allowed_when_no_failures(db_session):
    rate_limit.ensure_login_allowed(db_session, email=EMAIL, ip=IP)


def test_below_limit_still_allowed(db_session):
    fail(db_session, settings.login_max_failures_per_account_ip - 1)
    rate_limit.ensure_login_allowed(db_session, email=EMAIL, ip=IP)


def test_blocked_after_max_failures_for_same_account_and_ip(db_session):
    fail(db_session, settings.login_max_failures_per_account_ip)

    with pytest.raises(LoginThrottledError) as exc:
        rate_limit.ensure_login_allowed(db_session, email=EMAIL, ip=IP)

    retry_after = int(exc.value.headers["Retry-After"])
    assert 1 <= retry_after <= settings.login_window_minutes * 60


def test_other_ip_not_blocked_by_account_ip_limit(db_session):
    fail(db_session, settings.login_max_failures_per_account_ip)
    rate_limit.ensure_login_allowed(db_session, email=EMAIL, ip=OTHER_IP)


def test_other_email_same_ip_not_blocked_below_ip_limit(db_session):
    fail(db_session, settings.login_max_failures_per_account_ip)
    rate_limit.ensure_login_allowed(db_session, email="lain@example.com", ip=IP)


def test_ip_limit_blocks_across_emails(db_session):
    for i in range(settings.login_max_failures_per_ip):
        rate_limit.record_failed_login(
            db_session, email=f"user{i}@example.com", ip=IP
        )

    with pytest.raises(LoginThrottledError):
        rate_limit.ensure_login_allowed(
            db_session, email="baru@example.com", ip=IP
        )


def test_old_failures_expire(db_session):
    fail(db_session, settings.login_max_failures_per_account_ip)
    shift_back(db_session, settings.login_window_minutes + 1)

    rate_limit.ensure_login_allowed(db_session, email=EMAIL, ip=IP)


def test_retry_after_reflects_remaining_time(db_session):
    fail(db_session, settings.login_max_failures_per_account_ip)
    shift_back(db_session, settings.login_window_minutes - 1)

    with pytest.raises(LoginThrottledError) as exc:
        rate_limit.ensure_login_allowed(db_session, email=EMAIL, ip=IP)

    assert 1 <= int(exc.value.headers["Retry-After"]) <= 61


def test_clear_failed_logins_only_affects_that_account_and_ip(db_session):
    fail(db_session, 3)
    fail(db_session, 2, ip=OTHER_IP)

    rate_limit.clear_failed_logins(db_session, email=EMAIL, ip=IP)

    assert count_rows(db_session) == 2


def test_email_is_not_stored_in_plain_text(db_session):
    fail(db_session, 1)

    row = db_session.execute(select(LoginAttempt)).scalar_one()
    assert row.email_hash != EMAIL
    assert len(row.email_hash) == 64


def test_email_fingerprint_is_case_and_space_insensitive():
    assert rate_limit.email_fingerprint(
        " Budi@Example.com "
    ) == rate_limit.email_fingerprint(EMAIL)
    assert rate_limit.email_fingerprint(EMAIL) != rate_limit.email_fingerprint(
        "lain@example.com"
    )


def test_purge_old_attempts(db_session):
    fail(db_session, 3)
    shift_back(db_session, settings.login_window_minutes + 1)
    fail(db_session, 1)

    removed = rate_limit.purge_old_attempts(db_session)

    assert removed == 3
    assert count_rows(db_session) == 1
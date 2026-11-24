from datetime import UTC, datetime, timedelta

import pytest

from app.core.timezones import DEFAULT_TIMEZONE, get_zone, is_valid_timezone
from app.modules.identity.models import User
from tests.helpers import PASSWORD, csrf_headers, sign_up_and_login
from tests.ledger_helpers import expect_rejected, make_user

REGISTER = "/api/v1/auth/register"
ME = "/api/v1/auth/me"


@pytest.fixture
def me(client):
    sign_up_and_login(client, "budi@example.com")
    return client


# ---------- modul zona waktu ----------


@pytest.mark.parametrize("name", ["Asia/Makassar", "UTC"])
def test_known_timezones_are_valid(name):
    assert is_valid_timezone(name) is True


@pytest.mark.parametrize("name", ["Mars/Phobos", "", "../etc/passwd"])
def test_unknown_timezones_are_invalid(name):
    assert is_valid_timezone(name) is False


def test_makassar_is_utc_plus_eight():
    moment = datetime(2026, 1, 1, tzinfo=UTC).astimezone(
        get_zone("Asia/Makassar")
    )

    assert moment.utcoffset() == timedelta(hours=8)


# ---------- model ----------


def test_new_user_gets_the_default_timezone(db_session):
    user = make_user(db_session)
    db_session.refresh(user)

    assert user.timezone == DEFAULT_TIMEZONE == "Asia/Makassar"


def test_blank_timezone_is_rejected_by_the_database(db_session):
    expect_rejected(
        db_session,
        User(
            email="x@example.com",
            password_hash="hash",
            full_name="Nama",
            timezone="   ",
        ),
    )


# ---------- API ----------


def register_payload(**extra):
    return {
        "email": "baru@example.com",
        "password": PASSWORD,
        "full_name": "Nama",
        **extra,
    }


def test_register_without_timezone_uses_the_default(client):
    response = client.post(REGISTER, json=register_payload())

    assert response.status_code == 201
    assert response.json()["timezone"] == "Asia/Makassar"


def test_register_with_a_custom_timezone(client):
    response = client.post(
        REGISTER, json=register_payload(timezone="Asia/Makassar")
    )

    assert response.status_code == 201
    assert response.json()["timezone"] == "Asia/Makassar"


def test_register_rejects_an_unknown_timezone(client):
    response = client.post(
        REGISTER, json=register_payload(timezone="Mars/Phobos")
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_user_can_change_the_timezone(me):
    response = me.patch(
        ME, json={"timezone": "Asia/Jayapura"}, headers=csrf_headers(me)
    )

    assert response.status_code == 200
    assert response.json()["timezone"] == "Asia/Jayapura"
    assert me.get(ME).json()["timezone"] == "Asia/Jayapura"


@pytest.mark.parametrize("value", ["Mars/Phobos", ""])
def test_changing_to_an_invalid_timezone_is_rejected(me, value):
    response = me.patch(
        ME, json={"timezone": value}, headers=csrf_headers(me)
    )

    assert response.status_code == 422
    assert me.get(ME).json()["timezone"] == "Asia/Makassar"


def test_changing_the_timezone_requires_a_csrf_token(me):
    response = me.patch(ME, json={"timezone": "Asia/Makassar"})

    assert response.status_code == 403
    assert me.get(ME).json()["timezone"] == "Asia/Makassar"


def test_changing_the_timezone_requires_login(client):
    response = client.patch(ME, json={"timezone": "Asia/Makassar"})

    assert response.status_code == 401


def test_profile_update_rejects_other_fields(me):
    response = me.patch(
        ME,
        json={"timezone": "Asia/Makassar", "full_name": "Orang Lain"},
        headers=csrf_headers(me),
    )

    assert response.status_code == 422
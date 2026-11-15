from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.core.config import settings
from app.modules.identity.models import User, UserSession

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"
CREDENTIALS = {"email": "budi@example.com", "password": "kata-sandi-panjang-1"}
COOKIE = settings.session_cookie_name
CSRF_COOKIE = settings.csrf_cookie_name


@pytest.fixture
def registered(client):
    response = client.post(REGISTER, json={**CREDENTIALS, "full_name": "Budi"})
    assert response.status_code == 201


def test_login_sets_cookie_and_me_works(client, registered):
    response = client.post(LOGIN, json=CREDENTIALS)

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "budi@example.com"
    assert "password" not in body
    assert "password_hash" not in body

    cookie_header = response.headers["set-cookie"].lower()
    assert f"{COOKIE}=" in cookie_header
    assert "httponly" in cookie_header
    assert "samesite=lax" in cookie_header

    me = client.get(ME)
    assert me.status_code == 200
    assert me.json()["email"] == "budi@example.com"


def test_login_email_is_case_insensitive(client, registered):
    response = client.post(
        LOGIN, json={**CREDENTIALS, "email": "BUDI@Example.com"}
    )
    assert response.status_code == 200


def test_login_wrong_password(client, registered):
    response = client.post(
        LOGIN, json={**CREDENTIALS, "password": "salah-salah-salah"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert COOKIE not in response.headers.get("set-cookie", "")


def test_login_unknown_email_looks_identical(client, registered):
    wrong_password = client.post(
        LOGIN, json={**CREDENTIALS, "password": "salah-salah-salah"}
    )
    unknown_email = client.post(
        LOGIN,
        json={"email": "tidak-ada@example.com", "password": "salah-salah-salah"},
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_me_requires_login(client):
    response = client.get(ME)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_garbage_cookie_is_rejected(client):
    response = client.get(ME, headers={"Cookie": f"{COOKIE}=token-ngawur"})
    assert response.status_code == 401


def test_token_is_stored_hashed(client, registered, db_session):
    client.post(LOGIN, json=CREDENTIALS)
    token = client.cookies.get(COOKIE)
    assert token

    session = db_session.execute(select(UserSession)).scalar_one()
    assert session.token_hash != token
    assert len(session.token_hash) == 64


def test_logout_revokes_session(client, registered, db_session):
    client.post(LOGIN, json=CREDENTIALS)
    token = client.cookies.get(COOKIE)
    csrf = client.cookies.get(CSRF_COOKIE)

    response = client.post(LOGOUT, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 204

    # Token lama dibawa lagi secara manual: harus ditolak server
    replay = client.get(ME, headers={"Cookie": f"{COOKIE}={token}"})
    assert replay.status_code == 401

    session = db_session.execute(select(UserSession)).scalar_one()
    assert session.revoked_at is not None


def test_logout_without_login_is_ok(client):
    assert client.post(LOGOUT).status_code == 204


def test_expired_session_is_rejected(client, registered, db_session):
    client.post(LOGIN, json=CREDENTIALS)
    db_session.execute(
        update(UserSession).values(
            expires_at=datetime.now(UTC) - timedelta(seconds=1)
        )
    )

    assert client.get(ME).status_code == 401


def test_inactive_user_cannot_login(client, registered, db_session):
    db_session.execute(update(User).values(is_active=False))

    response = client.post(LOGIN, json=CREDENTIALS)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_deactivated_user_loses_access(client, registered, db_session):
    client.post(LOGIN, json=CREDENTIALS)
    db_session.execute(update(User).values(is_active=False))

    assert client.get(ME).status_code == 401


def test_login_rotates_session(client, registered, db_session):
    client.post(LOGIN, json=CREDENTIALS)
    first = client.cookies.get(COOKIE)
    client.post(LOGIN, json=CREDENTIALS)
    second = client.cookies.get(COOKIE)

    assert first != second

    sessions = db_session.execute(select(UserSession)).scalars().all()
    assert len(sessions) == 2
    assert sum(1 for s in sessions if s.revoked_at is not None) == 1

    old = client.get(ME, headers={"Cookie": f"{COOKIE}={first}"})
    assert old.status_code == 401
    assert client.get(ME).status_code == 200
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import settings
from app.main import app
from app.modules.identity.models import LoginAttempt

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
EMAIL = "budi@example.com"
PASSWORD = "kata-sandi-panjang-1"
LIMIT = settings.login_max_failures_per_account_ip


@pytest.fixture
def registered(client):
    response = client.post(
        REGISTER,
        json={"email": EMAIL, "password": PASSWORD, "full_name": "Budi"},
    )
    assert response.status_code == 201


def bad_login(c, email=EMAIL):
    return c.post(LOGIN, json={"email": email, "password": "salah-salah-salah"})


def good_login(c):
    return c.post(LOGIN, json={"email": EMAIL, "password": PASSWORD})


def test_login_is_throttled_after_max_failures(client, registered):
    for _ in range(LIMIT):
        assert bad_login(client).status_code == 401

    response = bad_login(client)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_login_attempts"
    assert int(response.headers["Retry-After"]) > 0


def test_correct_password_is_rejected_while_blocked(client, registered):
    for _ in range(LIMIT):
        bad_login(client)

    response = good_login(client)

    assert response.status_code == 429
    assert settings.session_cookie_name not in response.headers.get(
        "set-cookie", ""
    )


def test_successful_login_resets_the_counter(client, registered):
    for _ in range(LIMIT - 1):
        assert bad_login(client).status_code == 401
    assert good_login(client).status_code == 200

    for _ in range(LIMIT - 1):
        assert bad_login(client).status_code == 401


def test_unknown_email_is_throttled_identically(client, registered):
    for _ in range(LIMIT):
        bad_login(client)
    for _ in range(LIMIT):
        bad_login(client, email="tidak-ada@example.com")

    known = bad_login(client)
    unknown = bad_login(client, email="tidak-ada@example.com")

    assert known.status_code == unknown.status_code == 429
    assert known.json() == unknown.json()


def test_blocked_attempts_are_not_recorded(client, registered, db_session):
    for _ in range(LIMIT + 3):
        bad_login(client)

    total = db_session.execute(
        select(func.count()).select_from(LoginAttempt)
    ).scalar_one()
    assert total == LIMIT


def test_other_ip_is_not_affected(client, registered):
    for _ in range(LIMIT):
        bad_login(client)
    assert bad_login(client).status_code == 429

    with TestClient(app, client=("203.0.113.9", 50000)) as other:
        assert good_login(other).status_code == 200
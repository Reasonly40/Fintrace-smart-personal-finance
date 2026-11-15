import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from app.modules.identity.models import UserSession

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"
SESSIONS = "/api/v1/auth/sessions"
PASSWORD = "kata-sandi-panjang-1"
CSRF_COOKIE = settings.csrf_cookie_name


def csrf_headers(c: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": c.cookies.get(CSRF_COOKIE)}


def login(c: TestClient, email: str) -> None:
    response = c.post(LOGIN, json={"email": email, "password": PASSWORD})
    assert response.status_code == 200


def sign_up_and_login(c: TestClient, email: str) -> None:
    response = c.post(
        REGISTER,
        json={"email": email, "password": PASSWORD, "full_name": "Nama"},
    )
    assert response.status_code == 201
    login(c, email)


@pytest.fixture
def alice(client):
    sign_up_and_login(client, "alice@example.com")
    return client


@pytest.fixture
def bob(second_client):
    sign_up_and_login(second_client, "bob@example.com")
    return second_client


def test_each_user_sees_only_own_sessions(alice, bob):
    a = alice.get(SESSIONS).json()
    b = bob.get(SESSIONS).json()

    assert len(a) == 1
    assert len(b) == 1
    assert a[0]["id"] != b[0]["id"]
    assert a[0]["is_current"] is True
    assert b[0]["is_current"] is True


def test_session_list_does_not_leak_token_material(alice):
    item = alice.get(SESSIONS).json()[0]

    assert set(item) == {"id", "created_at", "expires_at", "is_current"}


def test_user_cannot_revoke_another_users_session(alice, bob, db_session):
    bob_session_id = bob.get(SESSIONS).json()[0]["id"]

    response = alice.delete(
        f"{SESSIONS}/{bob_session_id}", headers=csrf_headers(alice)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"
    # Korban tetap login dan data di database tidak tersentuh
    assert bob.get(ME).status_code == 200
    revoked_at = db_session.execute(
        select(UserSession.revoked_at).where(
            UserSession.id == uuid.UUID(bob_session_id)
        )
    ).scalar_one()
    assert revoked_at is None


def test_foreign_and_nonexistent_ids_look_identical(alice, bob):
    bob_session_id = bob.get(SESSIONS).json()[0]["id"]

    foreign = alice.delete(
        f"{SESSIONS}/{bob_session_id}", headers=csrf_headers(alice)
    )
    missing = alice.delete(
        f"{SESSIONS}/{uuid.uuid4()}", headers=csrf_headers(alice)
    )

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


def test_user_can_revoke_own_other_session(alice):
    with TestClient(app) as phone:
        login(phone, "alice@example.com")

        sessions = alice.get(SESSIONS).json()
        assert len(sessions) == 2
        phone_session = next(s for s in sessions if not s["is_current"])

        response = alice.delete(
            f"{SESSIONS}/{phone_session['id']}", headers=csrf_headers(alice)
        )

        assert response.status_code == 204
        assert phone.get(ME).status_code == 401
        assert alice.get(ME).status_code == 200
        assert len(alice.get(SESSIONS).json()) == 1


def test_delete_session_requires_csrf_token(alice):
    session_id = alice.get(SESSIONS).json()[0]["id"]

    response = alice.delete(f"{SESSIONS}/{session_id}")

    assert response.status_code == 403
    assert alice.get(ME).status_code == 200


def test_sessions_require_login(client):
    assert client.get(SESSIONS).status_code == 401
    assert client.delete(f"{SESSIONS}/{uuid.uuid4()}").status_code == 401


def test_malformed_session_id_is_validation_error(alice):
    response = alice.delete(
        f"{SESSIONS}/bukan-uuid", headers=csrf_headers(alice)
    )

    assert response.status_code == 422


def test_identity_comes_from_session_not_request(alice, bob):
    bob_id = bob.get(ME).json()["id"]

    response = alice.get(ME, params={"user_id": bob_id})

    assert response.json()["email"] == "alice@example.com"
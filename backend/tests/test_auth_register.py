import pytest
from sqlalchemy import select

from app.modules.identity.models import User

URL = "/api/v1/auth/register"
VALID = {
    "email": "Budi@Example.com",
    "password": "kata-sandi-panjang-1",
    "full_name": "  Budi Santoso ",
}


def test_register_success(client, db_session):
    response = client.post(URL, json=VALID)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "budi@example.com"
    assert body["full_name"] == "Budi Santoso"
    assert "id" in body
    assert "password" not in body
    assert "password_hash" not in body

    user = db_session.execute(
        select(User).where(User.email == "budi@example.com")
    ).scalar_one()
    assert user.password_hash.startswith("$argon2id$")
    assert VALID["password"] not in user.password_hash


def test_register_duplicate_email_is_case_insensitive(client):
    assert client.post(URL, json=VALID).status_code == 201

    other = {**VALID, "email": "BUDI@example.com"}
    response = client.post(URL, json=other)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_already_registered"


@pytest.mark.parametrize(
    "override",
    [
        {"password": "abc123"},
        {"password": "x" * 129},
        {"email": "bukan-email"},
        {"full_name": "   "},
        {"full_name": ""},
    ],
)
def test_register_rejects_invalid_input(client, override):
    response = client.post(URL, json={**VALID, **override})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["fields"]


def test_register_missing_field(client):
    payload = {k: v for k, v in VALID.items() if k != "email"}
    response = client.post(URL, json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["field"] == "email"


def test_validation_error_does_not_echo_password(client):
    response = client.post(URL, json={**VALID, "password": "abc123"})

    assert response.status_code == 422
    assert "abc123" not in response.text
from fastapi.testclient import TestClient

from app.core.config import settings

PASSWORD = "kata-sandi-panjang-1"


def sign_up_and_login(c: TestClient, email: str) -> None:
    response = c.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "Nama"},
    )
    assert response.status_code == 201
    response = c.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200


def csrf_headers(c: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": c.cookies.get(settings.csrf_cookie_name)}
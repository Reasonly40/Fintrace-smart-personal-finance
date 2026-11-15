import pytest

from app.core.config import settings
from app.core.csrf import make_csrf_token

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"
CREDENTIALS = {"email": "budi@example.com", "password": "kata-sandi-panjang-1"}
COOKIE = settings.session_cookie_name
CSRF_COOKIE = settings.csrf_cookie_name
CSRF_HEADER = "X-CSRF-Token"
GOOD_ORIGIN = settings.allowed_origins_list[0]
EVIL_ORIGIN = "https://evil.example"


@pytest.fixture
def registered(client):
    response = client.post(REGISTER, json={**CREDENTIALS, "full_name": "Budi"})
    assert response.status_code == 201


@pytest.fixture
def logged_in(client, registered):
    assert client.post(LOGIN, json=CREDENTIALS).status_code == 200
    return client


def test_login_sets_session_cookie_hidden_and_csrf_cookie_readable(
    client, registered
):
    response = client.post(LOGIN, json=CREDENTIALS)

    headers = response.headers.get_list("set-cookie")
    session_cookie = next(h for h in headers if h.startswith(f"{COOKIE}="))
    csrf_cookie = next(h for h in headers if h.startswith(f"{CSRF_COOKIE}="))
    assert "httponly" in session_cookie.lower()
    assert "httponly" not in csrf_cookie.lower()


def test_logout_without_csrf_header_is_rejected(logged_in):
    response = logged_in.post(LOGOUT)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    # Sesi harus tetap hidup: permintaan palsu tidak boleh berefek
    assert logged_in.get(ME).status_code == 200


def test_logout_with_wrong_token_is_rejected(logged_in):
    response = logged_in.post(LOGOUT, headers={CSRF_HEADER: "token-ngawur"})

    assert response.status_code == 403
    assert logged_in.get(ME).status_code == 200


def test_token_from_another_session_is_rejected(logged_in):
    forged = make_csrf_token("token-sesi-milik-orang-lain")
    response = logged_in.post(LOGOUT, headers={CSRF_HEADER: forged})

    assert response.status_code == 403


def test_logout_with_valid_token_works(logged_in):
    token = logged_in.cookies.get(CSRF_COOKIE)
    response = logged_in.post(LOGOUT, headers={CSRF_HEADER: token})

    assert response.status_code == 204
    assert logged_in.get(ME).status_code == 401


def test_untrusted_origin_is_rejected_even_on_login(client, registered):
    response = client.post(
        LOGIN, json=CREDENTIALS, headers={"Origin": EVIL_ORIGIN}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    assert COOKIE not in response.headers.get("set-cookie", "")


def test_trusted_origin_is_accepted(client, registered):
    response = client.post(
        LOGIN, json=CREDENTIALS, headers={"Origin": GOOD_ORIGIN}
    )

    assert response.status_code == 200


def test_null_origin_is_rejected(client, registered):
    response = client.post(
        LOGIN, json=CREDENTIALS, headers={"Origin": "null"}
    )

    assert response.status_code == 403


def test_untrusted_referer_is_rejected_when_no_origin(client, registered):
    response = client.post(
        LOGIN,
        json=CREDENTIALS,
        headers={"Referer": f"{EVIL_ORIGIN}/halaman-jebakan"},
    )

    assert response.status_code == 403


def test_trusted_referer_is_accepted_when_no_origin(client, registered):
    response = client.post(
        LOGIN,
        json=CREDENTIALS,
        headers={"Referer": f"{GOOD_ORIGIN}/docs"},
    )

    assert response.status_code == 200


def test_safe_methods_skip_the_check(logged_in):
    response = logged_in.get(ME, headers={"Origin": EVIL_ORIGIN})

    assert response.status_code == 200


def test_csrf_token_changes_with_every_login(client, registered):
    client.post(LOGIN, json=CREDENTIALS)
    first = client.cookies.get(CSRF_COOKIE)
    client.post(LOGIN, json=CREDENTIALS)
    second = client.cookies.get(CSRF_COOKIE)

    assert first
    assert first != second
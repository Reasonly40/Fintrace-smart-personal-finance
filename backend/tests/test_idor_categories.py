import uuid

import pytest

from tests.api_helpers import (
    CATEGORIES,
    global_category,
    new_category,
)
from tests.helpers import csrf_headers, sign_up_and_login


@pytest.fixture
def alice(client):
    sign_up_and_login(client, "alice@example.com")
    return client


@pytest.fixture
def bob(second_client):
    sign_up_and_login(second_client, "bob@example.com")
    return second_client


def personal_names(c):
    items = c.get(
        CATEGORIES, params={"scope": "personal", "limit": 100}
    ).json()["items"]
    return [item["name"] for item in items]


def call(c, method, category_id):
    url = f"{CATEGORIES}/{category_id}"
    if method == "GET":
        return c.get(url)
    if method == "PATCH":
        return c.patch(url, json={"name": "Dibajak"}, headers=csrf_headers(c))
    return c.post(f"{url}/{method}", headers=csrf_headers(c))


def test_each_user_lists_only_own_personal_categories(alice, bob):
    new_category(alice, "Hobi Alice")
    new_category(bob, "Hobi Bob")

    assert personal_names(alice) == ["Hobi Alice"]
    assert personal_names(bob) == ["Hobi Bob"]


def test_global_categories_are_visible_to_everyone(alice, bob):
    for user in (alice, bob):
        body = user.get(CATEGORIES, params={"scope": "global"}).json()
        assert body["total"] == 16


def test_user_cannot_read_a_foreign_category(alice, bob):
    victim = new_category(bob, "Rahasia Bob")

    response = alice.get(f"{CATEGORIES}/{victim['id']}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "category_not_found"


@pytest.mark.parametrize("method", ["PATCH", "archive", "unarchive"])
def test_user_cannot_modify_a_foreign_category(alice, bob, method):
    victim = new_category(bob, "Rahasia Bob")

    response = call(alice, method, victim["id"])

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "category_not_found"
    # Korban tidak terpengaruh sama sekali
    assert bob.get(f"{CATEGORIES}/{victim['id']}").json() == victim


@pytest.mark.parametrize("method", ["GET", "PATCH", "archive", "unarchive"])
def test_foreign_and_nonexistent_ids_look_identical(alice, bob, method):
    victim = new_category(bob, "Rahasia Bob")

    foreign = call(alice, method, victim["id"])
    missing = call(alice, method, uuid.uuid4())

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


def test_same_personal_name_is_allowed_for_different_users(alice, bob):
    new_category(alice, "Kopi")
    new_category(bob, "Kopi")

    assert personal_names(alice) == ["Kopi"]
    assert personal_names(bob) == ["Kopi"]


def test_user_id_in_body_cannot_target_another_user(alice, bob):
    bob_id = bob.get("/api/v1/auth/me").json()["id"]

    response = alice.post(
        CATEGORIES,
        json={"name": "Salah Alamat", "category_type": "EXPENSE", "user_id": bob_id},
        headers=csrf_headers(alice),
    )

    assert response.status_code == 422
    assert personal_names(bob) == []


def test_a_global_category_cannot_be_hijacked_by_another_user(alice, bob):
    gaji = global_category(alice, "Gaji", "INCOME")

    response = call(bob, "PATCH", gaji["id"])

    assert response.status_code == 403
    assert alice.get(f"{CATEGORIES}/{gaji['id']}").json()["name"] == "Gaji"


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", CATEGORIES, None),
        ("POST", CATEGORIES, {"name": "X", "category_type": "EXPENSE"}),
        ("GET", f"{CATEGORIES}/{uuid.uuid4()}", None),
        ("PATCH", f"{CATEGORIES}/{uuid.uuid4()}", {"name": "X"}),
        ("POST", f"{CATEGORIES}/{uuid.uuid4()}/archive", None),
        ("POST", f"{CATEGORIES}/{uuid.uuid4()}/unarchive", None),
    ],
)
def test_category_endpoints_require_login(client, method, path, payload):
    kwargs = {"json": payload} if payload is not None else {}

    response = client.request(method, path, **kwargs)

    assert response.status_code == 401
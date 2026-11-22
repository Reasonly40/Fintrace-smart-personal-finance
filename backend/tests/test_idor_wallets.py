import uuid

import pytest
from sqlalchemy import select

from app.modules.wallet.models import Wallet
from tests.helpers import csrf_headers, sign_up_and_login

WALLETS = "/api/v1/wallets"
ME = "/api/v1/auth/me"

# (method, suffix di belakang /wallets/{id}, body)
ATTACKS = [
    ("GET", "", None),
    ("PATCH", "", {"name": "Dibajak"}),
    ("POST", "/archive", None),
]


@pytest.fixture
def alice(client):
    sign_up_and_login(client, "alice@example.com")
    return client


@pytest.fixture
def bob(second_client):
    sign_up_and_login(second_client, "bob@example.com")
    return second_client


def create(c, name):
    response = c.post(
        WALLETS,
        json={"name": name, "wallet_type": "BANK"},
        headers=csrf_headers(c),
    )
    assert response.status_code == 201
    return response.json()


def call(c, method, url, payload=None):
    kwargs = {}
    if method != "GET":
        kwargs["headers"] = csrf_headers(c)
    if payload is not None:
        kwargs["json"] = payload
    return c.request(method, url, **kwargs)


def test_each_user_lists_only_own_wallets(alice, bob):
    create(alice, "Milik Alice")
    create(bob, "Milik Bob")

    a = alice.get(WALLETS).json()
    b = bob.get(WALLETS).json()

    assert [w["name"] for w in a["items"]] == ["Milik Alice"]
    assert [w["name"] for w in b["items"]] == ["Milik Bob"]
    assert a["total"] == 1
    assert b["total"] == 1


def test_wallet_belongs_to_the_session_user(alice, db_session):
    alice_id = alice.get(ME).json()["id"]

    wallet = create(alice, "BCA")

    owner = db_session.execute(
        select(Wallet.user_id).where(Wallet.id == uuid.UUID(wallet["id"]))
    ).scalar_one()
    assert str(owner) == alice_id


@pytest.mark.parametrize(("method", "suffix", "payload"), ATTACKS)
def test_user_cannot_touch_a_foreign_wallet(
    alice, bob, method, suffix, payload
):
    victim = create(bob, "Milik Bob")

    response = call(
        alice, method, f"{WALLETS}/{victim['id']}{suffix}", payload
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "wallet_not_found"
    # Korban tidak terpengaruh sama sekali
    assert bob.get(f"{WALLETS}/{victim['id']}").json() == victim


@pytest.mark.parametrize(("method", "suffix", "payload"), ATTACKS)
def test_foreign_and_nonexistent_ids_look_identical(
    alice, bob, method, suffix, payload
):
    victim = create(bob, "Milik Bob")

    foreign = call(
        alice, method, f"{WALLETS}/{victim['id']}{suffix}", payload
    )
    missing = call(alice, method, f"{WALLETS}/{uuid.uuid4()}{suffix}", payload)

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", WALLETS, None),
        ("POST", WALLETS, {"name": "X", "wallet_type": "BANK"}),
        ("GET", f"{WALLETS}/{uuid.uuid4()}", None),
        ("PATCH", f"{WALLETS}/{uuid.uuid4()}", {"name": "X"}),
        ("POST", f"{WALLETS}/{uuid.uuid4()}/archive", None),
    ],
)
def test_wallet_endpoints_require_login(client, method, path, payload):
    kwargs = {"json": payload} if payload is not None else {}

    response = client.request(method, path, **kwargs)

    assert response.status_code == 401


def test_user_id_in_body_cannot_target_another_user(alice, bob):
    bob_id = bob.get(ME).json()["id"]

    response = alice.post(
        WALLETS,
        json={"name": "Salah Alamat", "wallet_type": "BANK", "user_id": bob_id},
        headers=csrf_headers(alice),
    )

    assert response.status_code == 422
    assert bob.get(WALLETS).json()["total"] == 0
import uuid

import pytest

from tests.api_helpers import (
    TRANSACTIONS,
    WALLETS,
    balance_of,
    draft_body,
    fund,
    new_draft,
    new_key,
    new_wallet,
    post_tx,
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


def call(c, method, transaction_id):
    if method == "GET":
        return c.get(f"{TRANSACTIONS}/{transaction_id}")
    return post_tx(c, transaction_id)


def test_each_user_lists_only_own_transactions(alice, bob):
    mine = new_draft(
        alice, new_wallet(alice)["id"], description="Milik Alice"
    )
    theirs = new_draft(bob, new_wallet(bob)["id"], description="Milik Bob")

    a = alice.get(TRANSACTIONS).json()
    b = bob.get(TRANSACTIONS).json()

    assert [t["id"] for t in a["items"]] == [mine["id"]]
    assert [t["id"] for t in b["items"]] == [theirs["id"]]


def test_user_cannot_read_a_foreign_transaction(alice, bob):
    victim = new_draft(bob, new_wallet(bob)["id"])

    response = alice.get(f"{TRANSACTIONS}/{victim['id']}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "transaction_not_found"


def test_user_cannot_post_a_foreign_transaction(alice, bob):
    wallet = new_wallet(bob)
    victim = new_draft(bob, wallet["id"], "INCOME", 100_000)

    response = post_tx(alice, victim["id"])

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "transaction_not_found"
    # Korban tidak terpengaruh sama sekali
    assert bob.get(f"{TRANSACTIONS}/{victim['id']}").json() == victim
    assert balance_of(bob, wallet["id"]) == 0


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_foreign_and_nonexistent_ids_look_identical(alice, bob, method):
    victim = new_draft(bob, new_wallet(bob)["id"])

    foreign = call(alice, method, victim["id"])
    missing = call(alice, method, uuid.uuid4())

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


def test_cannot_create_a_draft_in_a_foreign_wallet(alice, bob):
    foreign_wallet = new_wallet(bob)

    foreign = alice.post(
        TRANSACTIONS,
        json=draft_body(foreign_wallet["id"]),
        headers=csrf_headers(alice),
    )
    missing = alice.post(
        TRANSACTIONS,
        json=draft_body(str(uuid.uuid4())),
        headers=csrf_headers(alice),
    )

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert foreign.json()["error"]["code"] == "wallet_not_found"
    assert bob.get(TRANSACTIONS).json()["total"] == 0


def test_user_id_in_body_is_rejected(alice, bob):
    bob_id = bob.get("/api/v1/auth/me").json()["id"]
    wallet = new_wallet(alice)

    response = alice.post(
        TRANSACTIONS,
        json=draft_body(wallet["id"], user_id=bob_id),
        headers=csrf_headers(alice),
    )

    assert response.status_code == 422
    assert bob.get(TRANSACTIONS).json()["total"] == 0


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", TRANSACTIONS, None),
        ("POST", TRANSACTIONS, draft_body(str(uuid.uuid4()))),
        ("GET", f"{TRANSACTIONS}/{uuid.uuid4()}", None),
        ("POST", f"{TRANSACTIONS}/{uuid.uuid4()}/post", None),
    ],
)
def test_transaction_endpoints_require_login(client, method, path, payload):
    kwargs = {}
    if payload is not None:
        kwargs["json"] = payload
    if path.endswith("/post"):
        kwargs["headers"] = {"Idempotency-Key": new_key()}

    response = client.request(method, path, **kwargs)

    assert response.status_code == 401


def test_idempotency_keys_are_scoped_per_user(alice, bob):
    tx_alice = new_draft(alice, new_wallet(alice)["id"])
    tx_bob = new_draft(bob, new_wallet(bob)["id"])
    key = new_key()

    first = post_tx(alice, tx_alice["id"], key)
    second = post_tx(bob, tx_bob["id"], key)

    assert first.status_code == second.status_code == 200
    assert "Idempotent-Replay" not in first.headers
    assert "Idempotent-Replay" not in second.headers


def test_balances_are_isolated_between_users(alice, bob):
    alice_wallet = new_wallet(alice)
    bob_wallet = new_wallet(bob)
    fund(alice, alice_wallet["id"], 100_000)

    assert balance_of(bob, bob_wallet["id"]) == 0
    assert bob.get(f"{WALLETS}/{alice_wallet['id']}").status_code == 404
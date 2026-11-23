import uuid

import pytest

from tests.api_helpers import (
    TRANSACTIONS,
    balance_of,
    fund,
    new_key,
    new_wallet,
    reverse_ok,
    reverse_tx,
)
from tests.helpers import sign_up_and_login


@pytest.fixture
def alice(client):
    sign_up_and_login(client, "alice@example.com")
    return client


@pytest.fixture
def bob(second_client):
    sign_up_and_login(second_client, "bob@example.com")
    return second_client


def test_user_cannot_reverse_a_foreign_transaction(alice, bob):
    wallet = new_wallet(bob)
    victim = fund(bob, wallet["id"], 100_000)

    response = reverse_tx(alice, victim["id"])

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "transaction_not_found"
    # Korban tidak terpengaruh sama sekali
    assert bob.get(f"{TRANSACTIONS}/{victim['id']}").json() == victim
    assert balance_of(bob, wallet["id"]) == 100_000
    reversals = bob.get(
        TRANSACTIONS, params={"transaction_type": "REVERSAL"}
    ).json()
    assert reversals["total"] == 0


def test_foreign_and_nonexistent_ids_look_identical(alice, bob):
    victim = fund(bob, new_wallet(bob)["id"], 100_000)

    foreign = reverse_tx(alice, victim["id"])
    missing = reverse_tx(alice, uuid.uuid4())

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


def test_reversal_works_independently_for_each_user(alice, bob):
    alice_income = fund(alice, new_wallet(alice)["id"], 100_000)
    bob_income = fund(bob, new_wallet(bob)["id"], 50_000)

    reverse_ok(alice, alice_income["id"])

    assert alice.get(f"{TRANSACTIONS}/{alice_income['id']}").json()[
        "status"
    ] == "REVERSED"
    assert bob.get(f"{TRANSACTIONS}/{bob_income['id']}").json()[
        "status"
    ] == "POSTED"


def test_idempotency_keys_are_scoped_per_user(alice, bob):
    alice_income = fund(alice, new_wallet(alice)["id"], 100_000)
    bob_income = fund(bob, new_wallet(bob)["id"], 100_000)
    key = new_key()

    first = reverse_tx(alice, alice_income["id"], key)
    second = reverse_tx(bob, bob_income["id"], key)

    assert first.status_code == second.status_code == 200
    assert "Idempotent-Replay" not in first.headers
    assert "Idempotent-Replay" not in second.headers
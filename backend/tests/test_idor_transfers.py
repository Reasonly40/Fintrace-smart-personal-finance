import uuid

import pytest

from tests.api_helpers import (
    TRANSACTIONS,
    balance_of,
    new_wallet,
    transfer_body,
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


def attempt(c, source_id, destination_id):
    return c.post(
        TRANSACTIONS,
        json=transfer_body(source_id, destination_id),
        headers=csrf_headers(c),
    )


@pytest.mark.parametrize("foreign_side", ["source", "destination"])
def test_foreign_wallet_in_a_transfer_looks_like_a_missing_wallet(
    alice, bob, foreign_side
):
    mine = new_wallet(alice, "Milik Alice")
    theirs = new_wallet(bob, "Milik Bob")
    ghost = {"id": str(uuid.uuid4())}
    source = theirs if foreign_side == "source" else mine
    destination = theirs if foreign_side == "destination" else mine
    ghost_source = ghost if foreign_side == "source" else mine
    ghost_destination = ghost if foreign_side == "destination" else mine

    foreign = attempt(alice, source["id"], destination["id"])
    missing = attempt(alice, ghost_source["id"], ghost_destination["id"])

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert foreign.json()["error"]["code"] == "wallet_not_found"
    # Korban tidak terpengaruh sama sekali
    assert bob.get(TRANSACTIONS).json()["total"] == 0
    assert balance_of(bob, theirs["id"]) == 0
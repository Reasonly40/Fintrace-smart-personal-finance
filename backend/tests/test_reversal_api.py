import uuid

import pytest

from tests.api_helpers import (
    TRANSACTIONS,
    balance_of,
    fund,
    new_draft,
    new_key,
    new_transfer,
    new_wallet,
    post_ok,
    reverse_ok,
    reverse_tx,
    spend,
)
from tests.helpers import csrf_headers, sign_up_and_login


@pytest.fixture
def me(client):
    sign_up_and_login(client, "budi@example.com")
    return client


def detail(c, transaction_id):
    return c.get(f"{TRANSACTIONS}/{transaction_id}").json()


def test_reverse_income_neutralises_it(me):
    wallet = new_wallet(me)
    income = fund(me, wallet["id"], 100_000)

    response = reverse_tx(me, income["id"], reason="  Salah catat ")

    assert response.status_code == 200
    body = response.json()
    original, reversal = body["original"], body["reversal"]
    assert original["id"] == income["id"]
    assert original["status"] == "REVERSED"
    assert original["reversed_by_id"] == reversal["id"]
    assert reversal["transaction_type"] == "REVERSAL"
    assert reversal["status"] == "POSTED"
    assert reversal["reversal_of_id"] == income["id"]
    assert reversal["amount"] == 100_000
    assert reversal["description"] == "Salah catat"
    assert [e["entry_type"] for e in reversal["entries"]] == ["DEBIT", "CREDIT"]
    assert reversal["entries"][0]["account_code"] == "INCOME_CONTROL"
    assert reversal["entries"][1]["account_name"] == "BCA"
    assert balance_of(me, wallet["id"]) == 0


def test_reverse_requires_an_idempotency_key(me):
    wallet = new_wallet(me)
    income = fund(me, wallet["id"], 100_000)

    response = me.post(
        f"{TRANSACTIONS}/{income['id']}/reverse",
        json={"reason": "Salah"},
        headers=csrf_headers(me),
    )

    assert response.status_code == 422
    fields = response.json()["error"]["fields"]
    assert fields[0]["field"] == "idempotency-key"
    assert detail(me, income["id"])["status"] == "POSTED"


def test_reverse_requires_csrf_token(me):
    wallet = new_wallet(me)
    income = fund(me, wallet["id"], 100_000)

    response = me.post(
        f"{TRANSACTIONS}/{income['id']}/reverse",
        json={"reason": "Salah"},
        headers={"Idempotency-Key": new_key()},
    )

    assert response.status_code == 403
    assert detail(me, income["id"])["status"] == "POSTED"
    assert balance_of(me, wallet["id"]) == 100_000


def test_reverse_requires_login(client):
    response = client.post(
        f"{TRANSACTIONS}/{uuid.uuid4()}/reverse",
        json={"reason": "Salah"},
        headers={"Idempotency-Key": new_key()},
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"reason": "   "},
        {"reason": "x" * 501},
        {"reason": "Salah", "amount": 1},
    ],
)
def test_reverse_rejects_an_invalid_reason(me, payload):
    wallet = new_wallet(me)
    income = fund(me, wallet["id"], 100_000)

    response = me.post(
        f"{TRANSACTIONS}/{income['id']}/reverse",
        json=payload,
        headers={**csrf_headers(me), "Idempotency-Key": new_key()},
    )

    assert response.status_code == 422
    assert detail(me, income["id"])["status"] == "POSTED"


def test_reverse_replays_without_reversing_twice(me):
    wallet = new_wallet(me)
    income = fund(me, wallet["id"], 100_000)
    key = new_key()
    first = reverse_tx(me, income["id"], key)

    second = reverse_tx(me, income["id"], key)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.headers["Idempotent-Replay"] == "true"
    assert second.json() == first.json()
    reversals = me.get(
        TRANSACTIONS, params={"transaction_type": "REVERSAL"}
    ).json()
    assert reversals["total"] == 1
    assert balance_of(me, wallet["id"]) == 0


def test_same_key_with_a_different_reason_is_a_conflict(me):
    wallet = new_wallet(me)
    income = fund(me, wallet["id"], 100_000)
    key = new_key()
    reverse_ok(me, income["id"], key, reason="Alasan satu")

    response = reverse_tx(me, income["id"], key, reason="Alasan dua")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_key_reused"


def test_draft_cannot_be_reversed(me):
    wallet = new_wallet(me)
    draft = new_draft(me, wallet["id"])

    response = reverse_tx(me, draft["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "transaction_not_posted"


def test_a_transaction_can_be_reversed_only_once(me):
    wallet = new_wallet(me)
    income = fund(me, wallet["id"], 100_000)
    reverse_ok(me, income["id"])

    response = reverse_tx(me, income["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "transaction_already_reversed"


def test_a_reversal_cannot_be_reversed(me):
    wallet = new_wallet(me)
    income = fund(me, wallet["id"], 100_000)
    reversal = reverse_ok(me, income["id"])["reversal"]

    response = reverse_tx(me, reversal["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "reversal_not_allowed"


def test_reversal_that_would_overdraw_is_rejected(me):
    wallet = new_wallet(me)
    income = fund(me, wallet["id"], 100_000)
    spend(me, wallet["id"], 80_000)

    response = reverse_tx(me, income["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "insufficient_balance"
    assert detail(me, income["id"])["status"] == "POSTED"
    assert balance_of(me, wallet["id"]) == 20_000


def test_reverse_unknown_transaction(me):
    response = reverse_tx(me, uuid.uuid4())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "transaction_not_found"


def test_reverse_with_malformed_id(me):
    assert reverse_tx(me, "bukan-uuid").status_code == 422


def test_original_history_is_kept_after_reversal(me):
    wallet = new_wallet(me)
    income = fund(me, wallet["id"], 100_000)
    reversal = reverse_ok(me, income["id"])["reversal"]

    original = detail(me, income["id"])

    assert original["status"] == "REVERSED"
    assert original["reversed_by_id"] == reversal["id"]
    assert original["entries"] == income["entries"]
    assert len(original["entries"]) == 2


def test_reversal_shows_up_in_the_transaction_list(me):
    wallet = new_wallet(me)
    income = fund(me, wallet["id"], 100_000)
    reversal = reverse_ok(me, income["id"])["reversal"]

    items = me.get(
        TRANSACTIONS, params={"transaction_type": "REVERSAL"}
    ).json()["items"]

    assert [item["id"] for item in items] == [reversal["id"]]
    assert items[0]["reversal_of_id"] == income["id"]


def test_correct_a_mistake_with_reversal_and_replacement(me):
    wallet = new_wallet(me)
    fund(me, wallet["id"], 100_000)
    wrong = spend(me, wallet["id"], 30_000)
    assert balance_of(me, wallet["id"]) == 70_000

    reverse_ok(me, wrong["id"], reason="Salah nominal")
    assert balance_of(me, wallet["id"]) == 100_000

    spend(me, wallet["id"], 20_000)
    assert balance_of(me, wallet["id"]) == 80_000


def test_reversing_a_transfer_restores_both_wallets(me):
    source = new_wallet(me, "BCA")
    target = new_wallet(me, "Dana", "E_WALLET")
    fund(me, source["id"], 100_000)
    transfer = new_transfer(me, source["id"], target["id"], 40_000)
    post_ok(me, transfer["id"])

    reverse_ok(me, transfer["id"])

    assert balance_of(me, source["id"]) == 100_000
    assert balance_of(me, target["id"]) == 0


def test_opening_balance_can_be_reversed_and_replaced(me):
    wallet = new_wallet(me)
    opening = new_draft(me, wallet["id"], "OPENING_BALANCE", 1_000_000)
    post_ok(me, opening["id"])

    reverse_ok(me, opening["id"], reason="Salah saldo awal")
    assert balance_of(me, wallet["id"]) == 0

    replacement = new_draft(me, wallet["id"], "OPENING_BALANCE", 500_000)
    post_ok(me, replacement["id"])
    assert balance_of(me, wallet["id"]) == 500_000
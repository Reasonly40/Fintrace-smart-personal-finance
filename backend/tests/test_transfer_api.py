import pytest

from tests.api_helpers import (
    OCCURRED,
    TRANSACTIONS,
    WALLETS,
    balance_of,
    draft_body,
    fund,
    new_key,
    new_transfer,
    new_wallet,
    post_ok,
    post_tx,
    transfer_body,
)
from tests.helpers import csrf_headers, sign_up_and_login

# (tipe, isian wallet); "A" dan "B" diganti ID wallet sungguhan
BAD_SHAPES = [
    ("TRANSFER", {"from_wallet_id": "A"}),
    ("TRANSFER", {"to_wallet_id": "A"}),
    (
        "TRANSFER",
        {"wallet_id": "A", "from_wallet_id": "A", "to_wallet_id": "B"},
    ),
    ("TRANSFER", {"from_wallet_id": "A", "to_wallet_id": "A"}),
    ("TRANSFER", {"wallet_id": "A"}),
    ("INCOME", {"wallet_id": "A", "from_wallet_id": "A"}),
    ("EXPENSE", {"wallet_id": "A", "to_wallet_id": "B"}),
]


@pytest.fixture
def me(client):
    sign_up_and_login(client, "budi@example.com")
    return client


def two_wallets(c):
    return new_wallet(c, "BCA"), new_wallet(c, "Dana", "E_WALLET")


def test_create_transfer_draft(me):
    source, destination = two_wallets(me)

    response = me.post(
        TRANSACTIONS,
        json=transfer_body(source["id"], destination["id"], 40_000),
        headers=csrf_headers(me),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["transaction_type"] == "TRANSFER"
    assert body["status"] == "DRAFT"
    assert body["amount"] == 40_000
    assert body["wallet_id"] is None
    assert body["from_wallet_id"] == source["id"]
    assert body["to_wallet_id"] == destination["id"]
    assert body["entries"] == []


@pytest.mark.parametrize(("kind", "fields"), BAD_SHAPES)
def test_create_rejects_wrong_wallet_fields(me, kind, fields):
    a, b = two_wallets(me)
    ids = {"A": a["id"], "B": b["id"]}
    body = {
        "transaction_type": kind,
        "amount": 1_000,
        "occurred_at": OCCURRED,
        **{key: ids[marker] for key, marker in fields.items()},
    }

    response = me.post(TRANSACTIONS, json=body, headers=csrf_headers(me))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_transfer_rejects_a_fractional_amount(me):
    source, destination = two_wallets(me)

    response = me.post(
        TRANSACTIONS,
        json=transfer_body(source["id"], destination["id"], 100.5),
        headers=csrf_headers(me),
    )

    assert response.status_code == 422


def test_posting_a_transfer_moves_money_between_wallets(me):
    source, destination = two_wallets(me)
    fund(me, source["id"], 100_000)
    draft = new_transfer(me, source["id"], destination["id"], 40_000)

    body = post_ok(me, draft["id"])

    assert body["status"] == "POSTED"
    entries = body["entries"]
    assert [e["entry_type"] for e in entries] == ["DEBIT", "CREDIT"]
    assert entries[0]["account_name"] == "Dana"
    assert entries[1]["account_name"] == "BCA"
    assert {e["amount"] for e in entries} == {40_000}
    assert balance_of(me, source["id"]) == 60_000
    assert balance_of(me, destination["id"]) == 40_000


def test_transfer_is_neither_income_nor_expense(me):
    source, destination = two_wallets(me)
    fund(me, source["id"], 100_000)
    draft = new_transfer(me, source["id"], destination["id"], 40_000)

    body = post_ok(me, draft["id"])

    codes = {e["account_code"] for e in body["entries"]}
    assert all(code.startswith("WALLET:") for code in codes)
    balances = [w["balance"] for w in me.get(WALLETS).json()["items"]]
    assert sum(balances) == 100_000


def test_transfer_above_the_source_balance_is_rejected(me):
    source, destination = two_wallets(me)
    fund(me, source["id"], 10_000)
    draft = new_transfer(me, source["id"], destination["id"], 20_000)

    response = post_tx(me, draft["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "insufficient_balance"
    detail = me.get(f"{TRANSACTIONS}/{draft['id']}").json()
    assert detail["status"] == "DRAFT"
    assert balance_of(me, source["id"]) == 10_000
    assert balance_of(me, destination["id"]) == 0


def test_transfer_post_replays_without_moving_money_twice(me):
    source, destination = two_wallets(me)
    fund(me, source["id"], 100_000)
    draft = new_transfer(me, source["id"], destination["id"], 40_000)
    key = new_key()
    first = post_tx(me, draft["id"], key)

    second = post_tx(me, draft["id"], key)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.headers["Idempotent-Replay"] == "true"
    assert second.json() == first.json()
    assert balance_of(me, source["id"]) == 60_000
    assert balance_of(me, destination["id"]) == 40_000


def test_transfer_appears_in_both_wallets_lists(me):
    source, destination = two_wallets(me)
    other = new_wallet(me, "Lain")
    draft = new_transfer(me, source["id"], destination["id"])

    for wallet in (source, destination):
        items = me.get(
            TRANSACTIONS, params={"wallet_id": wallet["id"]}
        ).json()["items"]
        assert draft["id"] in {item["id"] for item in items}

    unrelated = me.get(TRANSACTIONS, params={"wallet_id": other["id"]}).json()
    assert unrelated["total"] == 0


def test_transfer_to_an_archived_wallet_is_rejected(me):
    source, destination = two_wallets(me)
    archived = me.post(
        f"{WALLETS}/{destination['id']}/archive", headers=csrf_headers(me)
    )
    assert archived.status_code == 200

    response = me.post(
        TRANSACTIONS,
        json=transfer_body(source["id"], destination["id"]),
        headers=csrf_headers(me),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "wallet_not_active"


def test_opening_balance_is_rejected_after_receiving_a_transfer(me):
    source, destination = two_wallets(me)
    fund(me, source["id"], 100_000)
    transfer = new_transfer(me, source["id"], destination["id"], 40_000)
    post_ok(me, transfer["id"])
    opening = me.post(
        TRANSACTIONS,
        json=draft_body(destination["id"], "OPENING_BALANCE", 500_000),
        headers=csrf_headers(me),
    ).json()

    response = post_tx(me, opening["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "opening_balance_not_allowed"
    assert balance_of(me, destination["id"]) == 40_000
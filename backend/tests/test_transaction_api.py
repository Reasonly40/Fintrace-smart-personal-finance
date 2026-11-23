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
    post_ok,
    post_tx,
    spend,
)
from tests.helpers import csrf_headers, sign_up_and_login


@pytest.fixture
def me(client):
    sign_up_and_login(client, "budi@example.com")
    return client


def with_key(c, key):
    return {**csrf_headers(c), "Idempotency-Key": key}


# ---------- create ----------


def test_create_draft_success(me):
    wallet = new_wallet(me)

    response = me.post(
        TRANSACTIONS,
        json=draft_body(
            wallet["id"], "EXPENSE", 25_000, description="  Makan siang "
        ),
        headers=csrf_headers(me),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["transaction_type"] == "EXPENSE"
    assert body["status"] == "DRAFT"
    assert body["amount"] == 25_000
    assert body["currency"] == "IDR"
    assert body["wallet_id"] == wallet["id"]
    assert body["description"] == "Makan siang"
    assert body["posted_at"] is None
    assert body["entries"] == []
    assert "user_id" not in body
    assert balance_of(me, wallet["id"]) == 0


def test_create_requires_login(client):
    response = client.post(
        TRANSACTIONS, json=draft_body(str(uuid.uuid4()))
    )

    assert response.status_code == 401


def test_create_requires_csrf_token(me):
    wallet = new_wallet(me)

    response = me.post(TRANSACTIONS, json=draft_body(wallet["id"]))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    assert me.get(TRANSACTIONS).json()["total"] == 0


@pytest.mark.parametrize(
    "amount",
    [0, -1, 100.5, 100.0, "1000", True, 1_000_000_000_000_000],
)
def test_create_rejects_invalid_amounts(me, amount):
    wallet = new_wallet(me)

    response = me.post(
        TRANSACTIONS,
        json=draft_body(wallet["id"], amount=amount),
        headers=csrf_headers(me),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "override",
    [
        {"transaction_type": "CRYPTO"},
        {"occurred_at": "2026-11-10T08:00:00"},
        {"user_id": "11111111-1111-1111-1111-111111111111"},
        {"description": "x" * 501},
        {"wallet_id": "bukan-uuid"},
    ],
)
def test_create_rejects_invalid_body(me, override):
    wallet = new_wallet(me)
    body = {**draft_body(wallet["id"]), **override}

    response = me.post(TRANSACTIONS, json=body, headers=csrf_headers(me))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_create_rejects_a_missing_field(me):
    wallet = new_wallet(me)
    body = draft_body(wallet["id"])
    del body["amount"]

    response = me.post(TRANSACTIONS, json=body, headers=csrf_headers(me))

    assert response.status_code == 422


@pytest.mark.parametrize("kind", ["REVERSAL"])
def test_create_rejects_types_not_yet_supported(me, kind):
    wallet = new_wallet(me)

    response = me.post(
        TRANSACTIONS,
        json=draft_body(wallet["id"], kind),
        headers=csrf_headers(me),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_transaction_type"


def test_create_with_key_replays_the_first_result(me):
    wallet = new_wallet(me)
    headers = with_key(me, new_key())
    body = draft_body(wallet["id"])

    first = me.post(TRANSACTIONS, json=body, headers=headers)
    second = me.post(TRANSACTIONS, json=body, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.headers["Idempotent-Replay"] == "true"
    assert second.json() == first.json()
    assert me.get(TRANSACTIONS).json()["total"] == 1


def test_create_same_key_with_different_body_is_a_conflict(me):
    wallet = new_wallet(me)
    headers = with_key(me, new_key())
    me.post(TRANSACTIONS, json=draft_body(wallet["id"]), headers=headers)

    response = me.post(
        TRANSACTIONS,
        json=draft_body(wallet["id"], amount=200_000),
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_key_reused"
    assert me.get(TRANSACTIONS).json()["total"] == 1


def test_create_without_key_makes_separate_drafts(me):
    wallet = new_wallet(me)

    new_draft(me, wallet["id"])
    new_draft(me, wallet["id"])

    assert me.get(TRANSACTIONS).json()["total"] == 2


@pytest.mark.parametrize(
    "key", ["short", "has space key", "k" * 129, "bad/key!!"]
)
def test_create_rejects_a_malformed_idempotency_key(me, key):
    wallet = new_wallet(me)

    response = me.post(
        TRANSACTIONS,
        json=draft_body(wallet["id"]),
        headers=with_key(me, key),
    )

    assert response.status_code == 422


# ---------- post ----------


def test_post_income_creates_a_balanced_journal(me):
    wallet = new_wallet(me)
    draft = new_draft(me, wallet["id"], "INCOME", 100_000)

    body = post_ok(me, draft["id"])

    assert body["status"] == "POSTED"
    assert body["posted_at"] is not None
    entries = body["entries"]
    assert [e["entry_type"] for e in entries] == ["DEBIT", "CREDIT"]
    assert {e["amount"] for e in entries} == {100_000}
    assert entries[0]["account_name"] == "BCA"
    assert entries[1]["account_code"] == "INCOME_CONTROL"
    assert balance_of(me, wallet["id"]) == 100_000


def test_post_expense_reduces_the_balance(me):
    wallet = new_wallet(me)
    fund(me, wallet["id"], 100_000)
    draft = new_draft(me, wallet["id"], "EXPENSE", 30_000)

    body = post_ok(me, draft["id"])

    entries = body["entries"]
    assert entries[0]["account_code"] == "EXPENSE_CONTROL"
    assert entries[0]["entry_type"] == "DEBIT"
    assert entries[1]["account_name"] == "BCA"
    assert entries[1]["entry_type"] == "CREDIT"
    assert balance_of(me, wallet["id"]) == 70_000


def test_post_requires_an_idempotency_key(me):
    wallet = new_wallet(me)
    draft = new_draft(me, wallet["id"])

    response = me.post(
        f"{TRANSACTIONS}/{draft['id']}/post", headers=csrf_headers(me)
    )

    assert response.status_code == 422
    fields = response.json()["error"]["fields"]
    assert fields[0]["field"] == "idempotency-key"
    detail = me.get(f"{TRANSACTIONS}/{draft['id']}").json()
    assert detail["status"] == "DRAFT"


def test_post_requires_csrf_token(me):
    wallet = new_wallet(me)
    draft = new_draft(me, wallet["id"])

    response = me.post(
        f"{TRANSACTIONS}/{draft['id']}/post",
        headers={"Idempotency-Key": new_key()},
    )

    assert response.status_code == 403
    assert balance_of(me, wallet["id"]) == 0


def test_post_replays_without_posting_again(me):
    wallet = new_wallet(me)
    draft = new_draft(me, wallet["id"], "INCOME", 100_000)
    key = new_key()
    first = post_tx(me, draft["id"], key)

    second = post_tx(me, draft["id"], key)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.headers["Idempotent-Replay"] == "true"
    assert second.json() == first.json()
    assert len(second.json()["entries"]) == 2
    assert balance_of(me, wallet["id"]) == 100_000


def test_post_same_key_for_a_different_transaction_is_a_conflict(me):
    wallet = new_wallet(me)
    first = new_draft(me, wallet["id"], "INCOME", 100_000)
    second = new_draft(me, wallet["id"], "INCOME", 50_000)
    key = new_key()
    post_ok(me, first["id"], key)

    response = post_tx(me, second["id"], key)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_key_reused"
    detail = me.get(f"{TRANSACTIONS}/{second['id']}").json()
    assert detail["status"] == "DRAFT"
    assert balance_of(me, wallet["id"]) == 100_000


def test_posting_twice_with_different_keys_is_a_conflict(me):
    wallet = new_wallet(me)
    draft = new_draft(me, wallet["id"], "INCOME", 100_000)
    post_ok(me, draft["id"])

    response = post_tx(me, draft["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "transaction_not_draft"
    assert balance_of(me, wallet["id"]) == 100_000


def test_expense_above_the_balance_is_rejected(me):
    wallet = new_wallet(me)
    draft = new_draft(me, wallet["id"], "EXPENSE", 50_000)

    response = post_tx(me, draft["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "insufficient_balance"
    detail = me.get(f"{TRANSACTIONS}/{draft['id']}").json()
    assert detail["status"] == "DRAFT"
    assert balance_of(me, wallet["id"]) == 0


def test_opening_balance_posts_against_equity(me):
    wallet = new_wallet(me)
    draft = new_draft(me, wallet["id"], "OPENING_BALANCE", 1_000_000)

    body = post_ok(me, draft["id"])

    assert body["entries"][0]["account_name"] == "BCA"
    assert body["entries"][1]["account_code"] == "OPENING_BALANCE_EQUITY"
    assert balance_of(me, wallet["id"]) == 1_000_000


def test_opening_balance_is_rejected_after_activity(me):
    wallet = new_wallet(me)
    fund(me, wallet["id"], 100_000)
    draft = new_draft(me, wallet["id"], "OPENING_BALANCE", 500_000)

    response = post_tx(me, draft["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "opening_balance_not_allowed"
    assert balance_of(me, wallet["id"]) == 100_000


def test_post_to_an_archived_wallet_is_rejected(me):
    wallet = new_wallet(me)
    draft = new_draft(me, wallet["id"])
    archived = me.post(
        f"{WALLETS}/{wallet['id']}/archive", headers=csrf_headers(me)
    )
    assert archived.status_code == 200

    response = post_tx(me, draft["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "wallet_not_active"


def test_post_unknown_transaction(me):
    response = post_tx(me, uuid.uuid4())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "transaction_not_found"


def test_post_with_malformed_id(me):
    response = post_tx(me, "bukan-uuid")

    assert response.status_code == 422


def test_failed_post_does_not_burn_the_key(me):
    wallet = new_wallet(me)
    draft = new_draft(me, wallet["id"], "EXPENSE", 50_000)
    key = new_key()
    failed = post_tx(me, draft["id"], key)
    assert failed.status_code == 409

    fund(me, wallet["id"], 100_000)
    retry = post_tx(me, draft["id"], key)

    assert retry.status_code == 200
    assert "Idempotent-Replay" not in retry.headers
    assert balance_of(me, wallet["id"]) == 50_000


# ---------- list ----------


def test_list_orders_by_occurred_at_newest_first(me):
    wallet = new_wallet(me)
    for day in (3, 1, 2):
        new_draft(
            me,
            wallet["id"],
            occurred_at=f"2026-11-0{day}T08:00:00Z",
            description=f"hari {day}",
        )

    items = me.get(TRANSACTIONS).json()["items"]

    assert [i["description"] for i in items] == ["hari 3", "hari 2", "hari 1"]


def test_list_filters_by_wallet_type_and_status(me):
    first = new_wallet(me, "A")
    second = new_wallet(me, "B")
    income = new_draft(me, first["id"], "INCOME", 1_000)
    post_ok(me, income["id"])
    new_draft(me, first["id"], "EXPENSE", 500)
    new_draft(me, second["id"], "INCOME", 700)

    def ids(**params):
        items = me.get(TRANSACTIONS, params=params).json()["items"]
        return {item["id"] for item in items}

    assert len(ids()) == 3
    assert len(ids(wallet_id=first["id"])) == 2
    assert len(ids(wallet_id=second["id"])) == 1
    assert len(ids(transaction_type="EXPENSE")) == 1
    assert ids(status="POSTED") == {income["id"]}
    assert len(ids(status="DRAFT", wallet_id=first["id"])) == 1


def test_list_filters_by_date_range(me):
    wallet = new_wallet(me)
    for day in (1, 2, 3):
        new_draft(
            me,
            wallet["id"],
            occurred_at=f"2026-11-0{day}T08:00:00Z",
            description=f"hari {day}",
        )

    def days(**params):
        items = me.get(TRANSACTIONS, params=params).json()["items"]
        return sorted(i["description"] for i in items)

    only_day_two = days(
        occurred_from="2026-11-02T00:00:00Z",
        occurred_to="2026-11-03T00:00:00Z",
    )
    from_day_two = days(occurred_from="2026-11-02T00:00:00Z")

    assert only_day_two == ["hari 2"]
    assert from_day_two == ["hari 2", "hari 3"]


def test_list_search_treats_wildcards_literally(me):
    wallet = new_wallet(me)
    for text_ in ("Kopi 100% enak", "Kopi manis", "Bensin motor"):
        new_draft(me, wallet["id"], description=text_)

    def found(query):
        items = me.get(TRANSACTIONS, params={"q": query}).json()["items"]
        return sorted(i["description"] for i in items)

    assert found("KOPI") == ["Kopi 100% enak", "Kopi manis"]
    assert found("100%") == ["Kopi 100% enak"]
    assert found("%") == ["Kopi 100% enak"]
    assert found("_") == []


def test_list_pagination_and_sort_by_amount(me):
    wallet = new_wallet(me)
    for amount in (3_000, 1_000, 2_000):
        new_draft(me, wallet["id"], amount=amount)
    params = {"limit": 2, "sort": "amount", "order": "asc"}

    first = me.get(TRANSACTIONS, params={**params, "page": 1}).json()
    second = me.get(TRANSACTIONS, params={**params, "page": 2}).json()

    assert first["total"] == 3
    assert [t["amount"] for t in first["items"]] == [1_000, 2_000]
    assert [t["amount"] for t in second["items"]] == [3_000]


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"limit": 0},
        {"limit": 101},
        {"sort": "user_id"},
        {"transaction_type": "CRYPTO"},
        {"status": "PENDING"},
        {
            "occurred_from": "2026-11-03T00:00:00Z",
            "occurred_to": "2026-11-02T00:00:00Z",
        },
        {"occurred_from": "2026-11-03T00:00:00"},
        {"q": "x" * 101},
    ],
)
def test_list_rejects_invalid_params(me, params):
    assert me.get(TRANSACTIONS, params=params).status_code == 422


# ---------- detail ----------


def test_detail_of_a_draft_has_no_entries(me):
    wallet = new_wallet(me)
    draft = new_draft(me, wallet["id"])

    response = me.get(f"{TRANSACTIONS}/{draft['id']}")

    assert response.status_code == 200
    assert response.json()["entries"] == []


def test_detail_after_posting_shows_the_journal(me):
    wallet = new_wallet(me)
    draft = new_draft(me, wallet["id"], "INCOME", 100_000)
    posted = post_ok(me, draft["id"])

    detail = me.get(f"{TRANSACTIONS}/{draft['id']}").json()

    assert detail["status"] == "POSTED"
    assert detail["entries"] == posted["entries"]


def test_detail_with_malformed_id(me):
    assert me.get(f"{TRANSACTIONS}/bukan-uuid").status_code == 422


# ---------- integrasi dengan wallet ----------


def test_wallet_balance_follows_posted_transactions(me):
    wallet = new_wallet(me)
    fund(me, wallet["id"], 100_000)
    spend(me, wallet["id"], 30_000)

    detail = me.get(f"{WALLETS}/{wallet['id']}").json()
    listed = me.get(WALLETS).json()["items"][0]

    assert detail["balance"] == 70_000
    assert listed["balance"] == 70_000


def test_wallet_can_be_archived_after_spending_everything(me):
    wallet = new_wallet(me)
    fund(me, wallet["id"], 100_000)
    url = f"{WALLETS}/{wallet['id']}/archive"

    blocked = me.post(url, headers=csrf_headers(me))
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "wallet_has_balance"

    spend(me, wallet["id"], 100_000)
    allowed = me.post(url, headers=csrf_headers(me))

    assert allowed.status_code == 200
    assert allowed.json()["is_active"] is False
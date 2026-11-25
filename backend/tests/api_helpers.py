import uuid

from tests.helpers import csrf_headers

WALLETS = "/api/v1/wallets"
TRANSACTIONS = "/api/v1/transactions"
OCCURRED = "2026-11-10T08:00:00Z"


def new_key() -> str:
    return f"key-{uuid.uuid4().hex}"


def new_wallet(c, name="BCA", wallet_type="BANK") -> dict:
    response = c.post(
        WALLETS,
        json={"name": name, "wallet_type": wallet_type},
        headers=csrf_headers(c),
    )
    assert response.status_code == 201, response.text
    return response.json()


def draft_body(
    wallet_id, kind="INCOME", amount=100_000, occurred_at=OCCURRED, **extra
) -> dict:
    body = {
        "transaction_type": kind,
        "wallet_id": wallet_id,
        "amount": amount,
        "occurred_at": occurred_at,
    }
    body.update(extra)
    return body


def new_draft(
    c, wallet_id, kind="INCOME", amount=100_000, occurred_at=OCCURRED, **extra
) -> dict:
    response = c.post(
        TRANSACTIONS,
        json=draft_body(wallet_id, kind, amount, occurred_at, **extra),
        headers=csrf_headers(c),
    )
    assert response.status_code == 201, response.text
    return response.json()


def post_tx(c, transaction_id, key=None):
    headers = {**csrf_headers(c), "Idempotency-Key": key or new_key()}
    return c.post(f"{TRANSACTIONS}/{transaction_id}/post", headers=headers)


def post_ok(c, transaction_id, key=None) -> dict:
    response = post_tx(c, transaction_id, key)
    assert response.status_code == 200, response.text
    return response.json()


def fund(c, wallet_id, amount) -> dict:
    draft = new_draft(c, wallet_id, "INCOME", amount)
    return post_ok(c, draft["id"])


def spend(c, wallet_id, amount) -> dict:
    draft = new_draft(c, wallet_id, "EXPENSE", amount)
    return post_ok(c, draft["id"])


def balance_of(c, wallet_id) -> int:
    return c.get(f"{WALLETS}/{wallet_id}").json()["balance"]

def transfer_body(
    source_id, destination_id, amount=40_000, occurred_at=OCCURRED, **extra
) -> dict:
    body = {
        "transaction_type": "TRANSFER",
        "from_wallet_id": source_id,
        "to_wallet_id": destination_id,
        "amount": amount,
        "occurred_at": occurred_at,
    }
    body.update(extra)
    return body


def new_transfer(
    c, source_id, destination_id, amount=40_000, occurred_at=OCCURRED, **extra
) -> dict:
    response = c.post(
        TRANSACTIONS,
        json=transfer_body(
            source_id, destination_id, amount, occurred_at, **extra
        ),
        headers=csrf_headers(c),
    )
    assert response.status_code == 201, response.text
    return response.json()

def reverse_tx(c, transaction_id, key=None, reason="Salah input"):
    headers = {**csrf_headers(c), "Idempotency-Key": key or new_key()}
    return c.post(
        f"{TRANSACTIONS}/{transaction_id}/reverse",
        json={"reason": reason},
        headers=headers,
    )


def reverse_ok(c, transaction_id, key=None, reason="Salah input") -> dict:
    response = reverse_tx(c, transaction_id, key, reason)
    assert response.status_code == 200, response.text
    return response.json()


CATEGORIES = "/api/v1/categories"


def new_category(c, name="Kopi", kind="EXPENSE", **extra) -> dict:
    response = c.post(
        CATEGORIES,
        json={"name": name, "category_type": kind, **extra},
        headers=csrf_headers(c),
    )
    assert response.status_code == 201, response.text
    return response.json()


def global_category(c, name, kind) -> dict:
    items = c.get(CATEGORIES, params={"q": name, "type": kind}).json()["items"]
    found = [item for item in items if item["name"] == name]
    assert len(found) == 1, items
    return found[0]
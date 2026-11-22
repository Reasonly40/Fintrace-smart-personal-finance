import uuid

import pytest
from sqlalchemy import select

from app.modules.financial_core.models import LedgerAccount
from tests.helpers import csrf_headers, sign_up_and_login

WALLETS = "/api/v1/wallets"


@pytest.fixture
def me(client):
    sign_up_and_login(client, "budi@example.com")
    return client


def create(c, name="BCA", wallet_type="BANK"):
    response = c.post(
        WALLETS,
        json={"name": name, "wallet_type": wallet_type},
        headers=csrf_headers(c),
    )
    assert response.status_code == 201
    return response.json()


def archive(c, wallet_id):
    response = c.post(
        f"{WALLETS}/{wallet_id}/archive", headers=csrf_headers(c)
    )
    assert response.status_code == 200
    return response.json()


# ---------- create ----------


def test_create_wallet_success(me):
    response = me.post(
        WALLETS,
        json={"name": "  BCA Utama ", "wallet_type": "BANK"},
        headers=csrf_headers(me),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "BCA Utama"
    assert body["wallet_type"] == "BANK"
    assert body["currency"] == "IDR"
    assert body["is_active"] is True
    assert body["archived_at"] is None
    assert "id" in body
    assert "user_id" not in body


def test_create_wallet_creates_asset_account_in_db(me, db_session):
    wallet = create(me)

    accounts = (
        db_session.execute(
            select(LedgerAccount).where(
                LedgerAccount.wallet_id == uuid.UUID(wallet["id"])
            )
        )
        .scalars()
        .all()
    )
    assert len(accounts) == 1
    assert accounts[0].account_type == "ASSET"


def test_create_wallet_requires_login(client):
    response = client.post(
        WALLETS, json={"name": "BCA", "wallet_type": "BANK"}
    )

    assert response.status_code == 401


def test_create_wallet_requires_csrf_token(me):
    response = me.post(WALLETS, json={"name": "BCA", "wallet_type": "BANK"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    assert me.get(WALLETS).json()["total"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "   ", "wallet_type": "BANK"},
        {"name": "x" * 101, "wallet_type": "BANK"},
        {"name": "BCA", "wallet_type": "CRYPTO"},
        {"wallet_type": "BANK"},
    ],
)
def test_create_wallet_rejects_invalid_input(me, payload):
    response = me.post(WALLETS, json=payload, headers=csrf_headers(me))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "extra", [{"user_id": str(uuid.uuid4())}, {"currency": "USD"}]
)
def test_create_wallet_rejects_unexpected_fields(me, extra):
    payload = {"name": "BCA", "wallet_type": "BANK", **extra}

    response = me.post(WALLETS, json=payload, headers=csrf_headers(me))

    assert response.status_code == 422


# ---------- list ----------


def test_list_defaults_to_active_wallets_only(me):
    create(me, "Aktif")
    old = create(me, "Lama")
    archive(me, old["id"])

    body = me.get(WALLETS).json()

    assert body["total"] == 1
    assert [w["name"] for w in body["items"]] == ["Aktif"]


def test_list_filters_by_status_and_type(me):
    create(me, "Bank A", "BANK")
    create(me, "Tunai", "CASH")
    closed = create(me, "Bank Lama", "BANK")
    archive(me, closed["id"])

    def names(**params):
        body = me.get(WALLETS, params=params).json()
        return sorted(w["name"] for w in body["items"])

    assert names() == ["Bank A", "Tunai"]
    assert names(status="archived") == ["Bank Lama"]
    assert names(status="all") == ["Bank A", "Bank Lama", "Tunai"]
    assert names(wallet_type="CASH") == ["Tunai"]
    assert names(status="all", wallet_type="BANK") == ["Bank A", "Bank Lama"]


def test_list_pagination(me):
    for name in ["A", "B", "C"]:
        create(me, name)
    params = {"limit": 2, "sort": "name", "order": "asc"}

    first = me.get(WALLETS, params={**params, "page": 1}).json()
    second = me.get(WALLETS, params={**params, "page": 2}).json()

    assert first["total"] == 3
    assert second["total"] == 3
    assert first["page"] == 1
    assert first["limit"] == 2
    assert [w["name"] for w in first["items"]] == ["A", "B"]
    assert [w["name"] for w in second["items"]] == ["C"]


@pytest.mark.parametrize(
    "params", [{"page": 0}, {"limit": 0}, {"limit": 101}]
)
def test_list_rejects_invalid_paging(me, params):
    assert me.get(WALLETS, params=params).status_code == 422


def test_list_sorts_by_name(me):
    for name in ["B", "C", "A"]:
        create(me, name)

    asc = me.get(WALLETS, params={"sort": "name", "order": "asc"}).json()
    desc = me.get(WALLETS, params={"sort": "name", "order": "desc"}).json()

    assert [w["name"] for w in asc["items"]] == ["A", "B", "C"]
    assert [w["name"] for w in desc["items"]] == ["C", "B", "A"]


def test_list_rejects_unknown_sort_field(me):
    response = me.get(WALLETS, params={"sort": "balance"})

    assert response.status_code == 422


# ---------- detail ----------


def test_get_wallet_detail(me):
    created = create(me)

    response = me.get(f"{WALLETS}/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_wallet_with_malformed_id(me):
    assert me.get(f"{WALLETS}/bukan-uuid").status_code == 422


# ---------- update ----------


def test_patch_updates_name_and_ledger_account(me, db_session):
    wallet = create(me, "BCA", "BANK")

    response = me.patch(
        f"{WALLETS}/{wallet['id']}",
        json={"name": "  BCA Gaji ", "wallet_type": "OTHER"},
        headers=csrf_headers(me),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "BCA Gaji"
    assert body["wallet_type"] == "OTHER"

    account = db_session.execute(
        select(LedgerAccount).where(
            LedgerAccount.wallet_id == uuid.UUID(wallet["id"])
        )
    ).scalar_one()
    db_session.refresh(account)
    assert account.account_name == "BCA Gaji"


def test_patch_requires_at_least_one_field(me):
    wallet = create(me)

    response = me.patch(
        f"{WALLETS}/{wallet['id']}", json={}, headers=csrf_headers(me)
    )

    assert response.status_code == 422


def test_patch_rejects_immutable_fields(me):
    wallet = create(me)

    response = me.patch(
        f"{WALLETS}/{wallet['id']}",
        json={"currency": "USD"},
        headers=csrf_headers(me),
    )

    assert response.status_code == 422


def test_patch_archived_wallet_is_a_conflict(me):
    wallet = create(me)
    archive(me, wallet["id"])

    response = me.patch(
        f"{WALLETS}/{wallet['id']}",
        json={"name": "Baru"},
        headers=csrf_headers(me),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "wallet_archived"


# ---------- archive ----------


def test_archive_wallet(me):
    wallet = create(me)

    body = archive(me, wallet["id"])

    assert body["is_active"] is False
    assert body["archived_at"] is not None
    # Masih bisa dibaca, tetapi tidak muncul di daftar default
    assert me.get(f"{WALLETS}/{wallet['id']}").status_code == 200
    assert me.get(WALLETS).json()["total"] == 0


def test_archive_twice_is_a_conflict(me):
    wallet = create(me)
    archive(me, wallet["id"])

    response = me.post(
        f"{WALLETS}/{wallet['id']}/archive", headers=csrf_headers(me)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "wallet_already_archived"


def test_archive_requires_csrf_token(me):
    wallet = create(me)

    response = me.post(f"{WALLETS}/{wallet['id']}/archive")

    assert response.status_code == 403
    assert me.get(f"{WALLETS}/{wallet['id']}").json()["is_active"] is True
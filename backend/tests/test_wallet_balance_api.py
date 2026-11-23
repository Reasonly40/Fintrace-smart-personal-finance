import uuid

import pytest

from app.modules.identity.models import User
from app.modules.wallet.models import Wallet
from tests.helpers import csrf_headers, sign_up_and_login
from tests.ledger_helpers import post_expense, post_income

WALLETS = "/api/v1/wallets"


@pytest.fixture
def me(client):
    sign_up_and_login(client, "budi@example.com")
    return client


def create(c, name="BCA"):
    response = c.post(
        WALLETS,
        json={"name": name, "wallet_type": "BANK"},
        headers=csrf_headers(c),
    )
    assert response.status_code == 201
    return response.json()


def rows(db, wallet_json):
    """Objek ORM wallet dan pemiliknya, untuk mengisi jurnal lewat helper."""
    wallet = db.get(Wallet, uuid.UUID(wallet_json["id"]))
    return db.get(User, wallet.user_id), wallet


def archive(c, wallet_id):
    return c.post(f"{WALLETS}/{wallet_id}/archive", headers=csrf_headers(c))


def test_new_wallet_reports_zero_balance(me):
    created = create(me)

    assert created["balance"] == 0
    assert me.get(f"{WALLETS}/{created['id']}").json()["balance"] == 0


def test_balance_reflects_the_ledger(me, db_session):
    wallet = create(me)
    user, row = rows(db_session, wallet)
    post_income(db_session, user, row, 100_000)
    post_expense(db_session, user, row, 30_000)

    detail = me.get(f"{WALLETS}/{wallet['id']}").json()
    listed = me.get(WALLETS).json()["items"][0]

    assert detail["balance"] == 70_000
    assert listed["balance"] == 70_000


def test_list_reports_each_wallets_own_balance(me, db_session):
    first = create(me, "Satu")
    second = create(me, "Dua")
    user, row_one = rows(db_session, first)
    _, row_two = rows(db_session, second)
    post_income(db_session, user, row_one, 100_000)
    post_income(db_session, user, row_two, 40_000)

    items = me.get(WALLETS).json()["items"]

    assert {w["name"]: w["balance"] for w in items} == {
        "Satu": 100_000,
        "Dua": 40_000,
    }


def test_wallet_with_balance_cannot_be_archived(me, db_session):
    wallet = create(me)
    user, row = rows(db_session, wallet)
    post_income(db_session, user, row, 100_000)

    response = archive(me, wallet["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "wallet_has_balance"
    assert me.get(f"{WALLETS}/{wallet['id']}").json()["is_active"] is True


def test_wallet_with_zero_balance_can_be_archived(me, db_session):
    wallet = create(me)
    user, row = rows(db_session, wallet)
    post_income(db_session, user, row, 100_000)
    post_expense(db_session, user, row, 100_000)

    response = archive(me, wallet["id"])

    assert response.status_code == 200
    assert response.json()["is_active"] is False
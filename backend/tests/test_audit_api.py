import pytest

from tests.api_helpers import WALLETS, new_wallet
from tests.helpers import csrf_headers, sign_up_and_login

AUDIT = "/api/v1/audit-logs"
LOGIN = "/api/v1/auth/login"


@pytest.fixture
def me(client):
    sign_up_and_login(client, "budi@example.com")
    return client


def actions(c, **params):
    items = c.get(AUDIT, params=params).json()["items"]
    return sorted(item["action"] for item in items)


def test_user_sees_own_activity(me):
    assert actions(me) == ["auth.login_succeeded", "auth.registered"]


def test_filters_by_action_resource_type_and_resource_id(me):
    wallet = new_wallet(me)
    me.post(f"{WALLETS}/{wallet['id']}/archive", headers=csrf_headers(me))

    assert actions(me, action="wallet.created") == ["wallet.created"]
    assert actions(me, resource_type="wallet") == [
        "wallet.archived",
        "wallet.created",
    ]
    assert actions(me, resource_id=wallet["id"]) == [
        "wallet.archived",
        "wallet.created",
    ]


def test_pagination(me):
    new_wallet(me)

    first = me.get(AUDIT, params={"limit": 2, "page": 1}).json()
    second = me.get(AUDIT, params={"limit": 2, "page": 2}).json()

    assert first["total"] == 3
    assert len(first["items"]) == 2
    assert len(second["items"]) == 1


@pytest.mark.parametrize(
    "params",
    [{"page": 0}, {"limit": 0}, {"limit": 101}, {"resource_id": "bukan-uuid"}],
)
def test_rejects_invalid_params(me, params):
    assert me.get(AUDIT, params=params).status_code == 422


def test_response_shape(me):
    item = me.get(AUDIT).json()["items"][0]

    assert set(item) == {
        "id",
        "action",
        "resource_type",
        "resource_id",
        "metadata",
        "ip_address",
        "created_at",
    }
    assert isinstance(item["metadata"], dict)
    assert item["ip_address"] == "testclient"


def test_requires_login(client):
    assert client.get(AUDIT).status_code == 401


def test_users_see_only_their_own_events(client, second_client):
    # Kejadian tanpa pengguna terkenal (login gagal, email tak terdaftar)
    client.post(
        LOGIN,
        json={"email": "hantu@example.com", "password": "salah-salah-1"},
    )
    sign_up_and_login(client, "alice@example.com")
    sign_up_and_login(second_client, "bob@example.com")
    new_wallet(second_client)

    alice = actions(client)
    bob = actions(second_client)

    assert "wallet.created" not in alice
    assert "auth.login_failed" not in alice
    assert "auth.login_failed" not in bob
    assert "wallet.created" in bob


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_audit_log_has_no_write_endpoints(me, method):
    response = me.request(
        method, AUDIT, json={}, headers=csrf_headers(me)
    )

    assert response.status_code == 405
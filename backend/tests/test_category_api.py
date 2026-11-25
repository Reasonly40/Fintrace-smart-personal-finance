import json
import uuid

import pytest
from sqlalchemy import select

from app.modules.operations.models import AuditLog
from tests.api_helpers import (
    CATEGORIES,
    global_category,
    new_category,
)
from tests.helpers import csrf_headers, sign_up_and_login

BASE = {"name": "Kopi", "category_type": "EXPENSE"}


@pytest.fixture
def me(client):
    sign_up_and_login(client, "budi@example.com")
    return client


def names(c, **params):
    body = c.get(CATEGORIES, params={"limit": 100, **params}).json()
    return [item["name"] for item in body["items"]]


def total(c, **params):
    return c.get(CATEGORIES, params=params).json()["total"]


def patch(c, category_id, payload):
    return c.patch(
        f"{CATEGORIES}/{category_id}", json=payload, headers=csrf_headers(c)
    )


def archive(c, category_id):
    return c.post(
        f"{CATEGORIES}/{category_id}/archive", headers=csrf_headers(c)
    )


def unarchive(c, category_id):
    return c.post(
        f"{CATEGORIES}/{category_id}/unarchive", headers=csrf_headers(c)
    )


def audit_rows(db, action):
    return (
        db.execute(select(AuditLog).where(AuditLog.action == action))
        .scalars()
        .all()
    )


# ---------- daftar dan baca ----------


def test_list_shows_the_global_categories_by_default(me):
    body = me.get(CATEGORIES, params={"limit": 100}).json()

    assert body["total"] == 16
    assert all(item["is_global"] for item in body["items"])
    assert all(item["is_active"] for item in body["items"])


def test_list_filters_by_type(me):
    assert sorted(names(me, type="INCOME")) == sorted(
        ["Gaji", "Bonus", "Usaha", "Investasi", "Hadiah", "Lainnya"]
    )
    assert len(names(me, type="EXPENSE")) == 10


def test_list_filters_by_scope(me):
    new_category(me, "Kopi")
    new_category(me, "Teh")

    assert total(me, scope="global") == 16
    assert total(me, scope="personal") == 2
    assert total(me, scope="all") == 18


def test_list_filters_by_status(me):
    kopi = new_category(me, "Kopi")
    new_category(me, "Teh")
    assert archive(me, kopi["id"]).status_code == 200

    assert "Kopi" not in names(me, scope="personal")
    assert names(me, scope="personal", status="archived") == ["Kopi"]
    assert sorted(names(me, scope="personal", status="all")) == ["Kopi", "Teh"]


def test_list_search_is_case_insensitive_and_literal(me):
    new_category(me, "Diskon 50%")

    assert names(me, q="MAKAN") == ["Makanan & Minuman"]
    assert names(me, q="50%") == ["Diskon 50%"]
    assert names(me, q="%") == ["Diskon 50%"]
    assert names(me, q="_") == []


def test_list_sorts_and_paginates(me):
    ascending = names(me, sort="name", order="asc")
    descending = names(me, sort="name", order="desc")
    assert descending == list(reversed(ascending))

    sizes = []
    for page in (1, 2, 3, 4):
        body = me.get(CATEGORIES, params={"limit": 5, "page": page}).json()
        sizes.append(len(body["items"]))
        assert body["total"] == 16
    assert sizes == [5, 5, 5, 1]


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"limit": 0},
        {"limit": 101},
        {"type": "TRANSFER"},
        {"scope": "semua"},
        {"status": "x"},
        {"sort": "user_id"},
        {"q": "x" * 81},
    ],
)
def test_list_rejects_invalid_params(me, params):
    assert me.get(CATEGORIES, params=params).status_code == 422


def test_list_response_shape(me):
    item = me.get(CATEGORIES).json()["items"][0]

    assert set(item) == {
        "id",
        "name",
        "category_type",
        "icon",
        "color",
        "is_active",
        "is_global",
        "created_at",
        "updated_at",
    }


def test_list_requires_login(client):
    assert client.get(CATEGORIES).status_code == 401


# ---------- create ----------


def test_create_personal_category(me):
    response = me.post(
        CATEGORIES,
        json={
            "name": "  Kopi Susu ",
            "category_type": "EXPENSE",
            "icon": "coffee",
            "color": "#abc123",
        },
        headers=csrf_headers(me),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Kopi Susu"
    assert body["category_type"] == "EXPENSE"
    assert body["icon"] == "coffee"
    assert body["color"] == "#ABC123"
    assert body["is_global"] is False
    assert body["is_active"] is True
    assert "user_id" not in body


def test_create_requires_csrf_token(me):
    response = me.post(CATEGORIES, json=BASE)

    assert response.status_code == 403
    assert total(me, scope="personal") == 0


def test_create_requires_login(client):
    assert client.post(CATEGORIES, json=BASE).status_code == 401


@pytest.mark.parametrize(
    "override",
    [
        {"name": "   "},
        {"name": "x" * 81},
        {"category_type": "TRANSFER"},
        {"color": "merah"},
        {"color": "#12345"},
        {"icon": "Ikon Besar!"},
        {"parent_id": "11111111-1111-1111-1111-111111111111"},
        {"user_id": "11111111-1111-1111-1111-111111111111"},
    ],
)
def test_create_rejects_invalid_input(me, override):
    response = me.post(
        CATEGORIES, json={**BASE, **override}, headers=csrf_headers(me)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "payload", [{"name": "Kopi"}, {"category_type": "EXPENSE"}]
)
def test_create_requires_name_and_type(me, payload):
    response = me.post(CATEGORIES, json=payload, headers=csrf_headers(me))

    assert response.status_code == 422


def test_duplicate_name_is_a_conflict_ignoring_case(me):
    new_category(me, "Kopi")

    response = me.post(
        CATEGORIES,
        json={"name": "KOPI", "category_type": "EXPENSE"},
        headers=csrf_headers(me),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "category_name_taken"


def test_same_name_is_allowed_for_the_other_type(me):
    new_category(me, "Kopi", "EXPENSE")

    new_category(me, "Kopi", "INCOME")


def test_name_equal_to_a_global_one_is_reserved(me):
    response = me.post(
        CATEGORIES,
        json={"name": "makanan & minuman", "category_type": "EXPENSE"},
        headers=csrf_headers(me),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "category_name_reserved"


def test_global_name_of_another_type_is_allowed(me):
    # "Gaji" adalah kategori bawaan bertipe INCOME, bukan EXPENSE
    new_category(me, "Gaji", "EXPENSE")


def test_archived_name_stays_reserved(me):
    kopi = new_category(me, "Kopi")
    archive(me, kopi["id"])

    response = me.post(
        CATEGORIES, json=BASE, headers=csrf_headers(me)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "category_name_taken"


# ---------- baca satu ----------


def test_get_a_global_category(me):
    gaji = global_category(me, "Gaji", "INCOME")

    response = me.get(f"{CATEGORIES}/{gaji['id']}")

    assert response.status_code == 200
    assert response.json()["is_global"] is True


def test_get_own_category(me):
    kopi = new_category(me, "Kopi")

    response = me.get(f"{CATEGORIES}/{kopi['id']}")

    assert response.status_code == 200
    assert response.json() == kopi


def test_get_unknown_category(me):
    response = me.get(f"{CATEGORIES}/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "category_not_found"


def test_get_with_malformed_id(me):
    assert me.get(f"{CATEGORIES}/bukan-uuid").status_code == 422


# ---------- update ----------


def test_patch_updates_name_icon_and_color(me):
    kopi = new_category(me, "Kopi")

    response = patch(
        me,
        kopi["id"],
        {"name": "Kopi Susu", "icon": "coffee", "color": "#00ff00"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Kopi Susu"
    assert body["icon"] == "coffee"
    assert body["color"] == "#00FF00"


def test_patch_can_clear_icon_and_color(me):
    kopi = new_category(me, "Kopi", icon="coffee", color="#112233")

    response = patch(me, kopi["id"], {"icon": None, "color": None})

    assert response.status_code == 200
    assert response.json()["icon"] is None
    assert response.json()["color"] is None


def test_patch_allows_changing_only_the_case_of_the_name(me):
    kopi = new_category(me, "Kopi")

    response = patch(me, kopi["id"], {"name": "KOPI"})

    assert response.status_code == 200
    assert response.json()["name"] == "KOPI"


def test_patch_to_an_existing_name_is_a_conflict(me):
    new_category(me, "Kopi")
    teh = new_category(me, "Teh")

    response = patch(me, teh["id"], {"name": "kopi"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "category_name_taken"


def test_patch_to_a_global_name_is_reserved(me):
    category = new_category(me, "Pemasukan Lain", "INCOME")

    response = patch(me, category["id"], {"name": "gaji"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "category_name_reserved"


def test_patch_requires_a_change(me):
    kopi = new_category(me, "Kopi")

    assert patch(me, kopi["id"], {}).status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"category_type": "INCOME"},
        {"parent_id": "11111111-1111-1111-1111-111111111111"},
        {"is_active": False},
    ],
)
def test_patch_rejects_immutable_fields(me, payload):
    kopi = new_category(me, "Kopi")

    assert patch(me, kopi["id"], payload).status_code == 422


def test_patch_rejects_a_null_name(me):
    kopi = new_category(me, "Kopi")

    assert patch(me, kopi["id"], {"name": None}).status_code == 422


def test_patch_global_category_is_forbidden(me):
    gaji = global_category(me, "Gaji", "INCOME")

    response = patch(me, gaji["id"], {"name": "Gaji Baru"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "category_read_only"
    assert me.get(f"{CATEGORIES}/{gaji['id']}").json()["name"] == "Gaji"


def test_patch_archived_category_is_a_conflict(me):
    kopi = new_category(me, "Kopi")
    archive(me, kopi["id"])

    response = patch(me, kopi["id"], {"name": "Kopi Baru"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "category_archived"


def test_patch_requires_csrf_token(me):
    kopi = new_category(me, "Kopi")

    response = me.patch(f"{CATEGORIES}/{kopi['id']}", json={"name": "Baru"})

    assert response.status_code == 403
    assert me.get(f"{CATEGORIES}/{kopi['id']}").json()["name"] == "Kopi"


# ---------- arsip ----------


def test_archive_personal_category(me):
    kopi = new_category(me, "Kopi")

    response = archive(me, kopi["id"])

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert "Kopi" not in names(me, scope="personal")
    assert me.get(f"{CATEGORIES}/{kopi['id']}").status_code == 200


def test_archive_twice_is_a_conflict(me):
    kopi = new_category(me, "Kopi")
    archive(me, kopi["id"])

    response = archive(me, kopi["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "category_already_archived"


@pytest.mark.parametrize("action", [archive, unarchive])
def test_global_categories_cannot_be_archived_or_restored(me, action):
    gaji = global_category(me, "Gaji", "INCOME")

    response = action(me, gaji["id"])

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "category_read_only"


def test_unarchive_restores_the_category(me):
    kopi = new_category(me, "Kopi")
    archive(me, kopi["id"])

    response = unarchive(me, kopi["id"])

    assert response.status_code == 200
    assert response.json()["is_active"] is True
    assert names(me, scope="personal") == ["Kopi"]


def test_unarchive_an_active_category_is_a_conflict(me):
    kopi = new_category(me, "Kopi")

    response = unarchive(me, kopi["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "category_not_archived"


def test_archive_requires_csrf_token(me):
    kopi = new_category(me, "Kopi")

    response = me.post(f"{CATEGORIES}/{kopi['id']}/archive")

    assert response.status_code == 403
    assert me.get(f"{CATEGORIES}/{kopi['id']}").json()["is_active"] is True


def test_categories_have_no_delete_endpoint(me):
    kopi = new_category(me, "Kopi")

    response = me.request(
        "DELETE", f"{CATEGORIES}/{kopi['id']}", headers=csrf_headers(me)
    )

    assert response.status_code == 405
    assert me.get(f"{CATEGORIES}/{kopi['id']}").status_code == 200


# ---------- audit ----------


def test_category_creation_is_audited(me, db_session):
    kopi = new_category(me, "Kopi")

    [row] = audit_rows(db_session, "category.created")
    assert row.resource_type == "category"
    assert row.resource_id == uuid.UUID(kopi["id"])
    assert row.event_metadata == {"category_type": "EXPENSE"}
    assert "Kopi" not in json.dumps(row.event_metadata)


def test_category_update_is_audited_with_field_names_only(me, db_session):
    kopi = new_category(me, "Kopi")

    patch(me, kopi["id"], {"name": "Nama Rahasia", "color": "#112233"})

    [row] = audit_rows(db_session, "category.updated")
    assert row.event_metadata == {"fields": ["name", "color"]}
    assert "Rahasia" not in json.dumps(row.event_metadata)


def test_category_archive_and_restore_are_audited(me, db_session):
    kopi = new_category(me, "Kopi")

    archive(me, kopi["id"])
    unarchive(me, kopi["id"])

    [archived] = audit_rows(db_session, "category.archived")
    [restored] = audit_rows(db_session, "category.unarchived")
    assert archived.resource_id == restored.resource_id == uuid.UUID(kopi["id"])


def test_rejected_changes_write_no_audit(me, db_session):
    new_category(me, "Kopi")

    duplicate = me.post(CATEGORIES, json=BASE, headers=csrf_headers(me))

    assert duplicate.status_code == 409
    assert len(audit_rows(db_session, "category.created")) == 1
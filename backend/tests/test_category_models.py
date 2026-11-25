import uuid

import pytest

from app.modules.classification.models import Category
from tests.ledger_helpers import expect_rejected, make_user


def personal(user, name="Kopi", kind="EXPENSE", **extra):
    return Category(user_id=user.id, name=name, category_type=kind, **extra)


def global_category(name="Kategori Uji Global", kind="EXPENSE", **extra):
    return Category(user_id=None, name=name, category_type=kind, **extra)


def test_category_gets_uuid_defaults_and_a_derived_key(db_session):
    user = make_user(db_session)
    category = personal(user, "Kopi Susu")
    db_session.add(category)
    db_session.flush()
    db_session.refresh(category)

    assert isinstance(category.id, uuid.UUID)
    assert category.is_active is True
    assert category.parent_id is None
    assert category.created_at.tzinfo is not None
    assert category.name_key == "kopi susu"


def test_category_type_must_be_known(db_session):
    user = make_user(db_session)

    expect_rejected(db_session, personal(user, kind="TRANSFER"))


@pytest.mark.parametrize("name", ["", "   ", " Makan", "Makan "])
def test_category_name_must_be_trimmed_and_not_blank(db_session, name):
    user = make_user(db_session)

    expect_rejected(db_session, personal(user, name))


@pytest.mark.parametrize("color", ["red", "#12345", "#GGGGGG", "123456"])
def test_category_color_must_be_hex(db_session, color):
    user = make_user(db_session)

    expect_rejected(db_session, personal(user, color=color))


def test_valid_color_and_icon_are_accepted(db_session):
    user = make_user(db_session)
    category = personal(user, color="#aBc123", icon="utensils")
    db_session.add(category)
    db_session.flush()

    assert category.color == "#aBc123"


def test_category_hierarchy_is_locked_in_the_mvp(db_session):
    user = make_user(db_session)
    parent = personal(user, "Induk")
    db_session.add(parent)
    db_session.flush()

    expect_rejected(db_session, personal(user, "Anak", parent_id=parent.id))


def test_personal_name_is_unique_per_user_and_type_ignoring_case(db_session):
    user = make_user(db_session)
    db_session.add(personal(user, "Kopi"))
    db_session.flush()

    expect_rejected(db_session, personal(user, "KOPI"))


def test_same_name_is_allowed_for_different_types(db_session):
    user = make_user(db_session)

    db_session.add_all(
        [personal(user, "Lainnya", "EXPENSE"), personal(user, "Lainnya", "INCOME")]
    )
    db_session.flush()


def test_same_name_is_allowed_for_different_users(db_session):
    first = make_user(db_session, "satu@example.com")
    second = make_user(db_session, "dua@example.com")

    db_session.add_all([personal(first, "Kopi"), personal(second, "Kopi")])
    db_session.flush()


def test_global_name_is_unique_per_type_ignoring_case(db_session):
    db_session.add(global_category("Kategori Uji Global"))
    db_session.flush()

    expect_rejected(db_session, global_category("KATEGORI UJI GLOBAL"))


def test_database_allows_a_personal_name_equal_to_a_global_name(db_session):
    # Larangan ini ditegakkan service di 3.3; index tidak bisa menjaganya
    user = make_user(db_session)

    db_session.add(personal(user, "Makanan & Minuman"))
    db_session.flush()


def test_category_requires_an_existing_user(db_session):
    expect_rejected(
        db_session,
        Category(
            user_id=uuid.uuid4(), name="Kopi", category_type="EXPENSE"
        ),
    )
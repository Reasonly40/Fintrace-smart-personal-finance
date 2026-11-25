from sqlalchemy import delete, func, select

from app.modules.classification.models import Category
from app.modules.classification.seed import (
    GLOBAL_CATEGORIES,
    ensure_global_categories,
)


def globals_in_db(db):
    rows = db.execute(
        select(
            Category.name,
            Category.category_type,
            Category.icon,
            Category.color,
        ).where(Category.user_id.is_(None))
    ).all()
    return {tuple(row) for row in rows}


def expected():
    return {
        (item.name, item.category_type.value, item.icon, item.color)
        for item in GLOBAL_CATEGORIES
    }


def count_globals(db, kind):
    return db.execute(
        select(func.count())
        .select_from(Category)
        .where(Category.user_id.is_(None), Category.category_type == kind)
    ).scalar_one()


def test_migration_data_matches_the_application_seed_list(db_session):
    # Mencegah salinan beku di migration dan seed.py menyimpang
    assert globals_in_db(db_session) == expected()


def test_seed_has_ten_expense_and_six_income_categories(db_session):
    assert count_globals(db_session, "EXPENSE") == 10
    assert count_globals(db_session, "INCOME") == 6


def test_other_exists_for_both_types(db_session):
    names = db_session.execute(
        select(Category.category_type).where(
            Category.user_id.is_(None), Category.name == "Lainnya"
        )
    ).scalars().all()

    assert sorted(names) == ["EXPENSE", "INCOME"]


def test_ensure_global_categories_is_idempotent(db_session):
    ensure_global_categories(db_session)
    ensure_global_categories(db_session)

    assert globals_in_db(db_session) == expected()
    assert count_globals(db_session, "EXPENSE") == 10


def test_ensure_global_categories_restores_a_deleted_one(db_session):
    db_session.execute(
        delete(Category).where(
            Category.user_id.is_(None), Category.name == "Gaji"
        )
    )
    assert ("Gaji", "INCOME", "wallet", "#16A34A") not in globals_in_db(
        db_session
    )

    ensure_global_categories(db_session)

    assert globals_in_db(db_session) == expected()
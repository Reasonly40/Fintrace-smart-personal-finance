from sqlalchemy import select

from app.modules.classification.models import Category


def default_category_id(db, kind):
    """ID kategori bawaan "Lainnya" untuk tipe INCOME atau EXPENSE."""
    kind = getattr(kind, "value", kind)
    return db.execute(
        select(Category.id).where(
            Category.user_id.is_(None),
            Category.name == "Lainnya",
            Category.category_type == kind,
        )
    ).scalar_one()


def make_category(db, user=None, name="Kopi", kind="EXPENSE", **extra):
    """Kategori personal (user diberikan) atau bawaan (user None)."""
    category = Category(
        user_id=user.id if user else None,
        name=name,
        category_type=kind,
        **extra,
    )
    db.add(category)
    db.flush()
    return category
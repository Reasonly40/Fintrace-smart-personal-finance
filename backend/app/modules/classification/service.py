import uuid
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.classification.enums import CategoryType
from app.modules.classification.errors import (
    CategoryAlreadyArchivedError,
    CategoryArchivedError,
    CategoryNameReservedError,
    CategoryNameTakenError,
    CategoryNotArchivedError,
    CategoryNotFoundError,
    CategoryReadOnlyError,
)
from app.modules.classification.models import Category
from app.modules.operations import audit

ScopeFilter = Literal["all", "global", "personal"]
StatusFilter = Literal["active", "archived", "all"]
SortField = Literal["name", "created_at"]
SortOrder = Literal["asc", "desc"]

# Allowlist kolom pengurutan: nilai dari klien tidak pernah masuk ke SQL.
# name_key (huruf kecil) membuat urutan nama tidak peka huruf besar kecil.
SORT_COLUMNS = {"name": Category.name_key, "created_at": Category.created_at}


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def get_category(
    db: Session,
    *,
    user_id: uuid.UUID,
    category_id: uuid.UUID,
    for_update: bool = False,
) -> Category:
    """Kategori yang terlihat oleh user: bawaan atau miliknya. Kategori
    personal milik orang lain sama saja dengan kategori yang tidak ada."""
    query = select(Category).where(
        Category.id == category_id,
        or_(Category.user_id.is_(None), Category.user_id == user_id),
    )
    if for_update:
        query = query.with_for_update()
    category = db.execute(query).scalar_one_or_none()
    if category is None:
        raise CategoryNotFoundError()
    return category


def _get_owned(
    db: Session, *, user_id: uuid.UUID, category_id: uuid.UUID
) -> Category:
    category = get_category(
        db, user_id=user_id, category_id=category_id, for_update=True
    )
    if category.user_id is None:
        raise CategoryReadOnlyError()
    return category


def _ensure_name_available(
    db: Session,
    *,
    user_id: uuid.UUID,
    category_type: str,
    name: str,
    exclude_id: uuid.UUID | None = None,
) -> None:
    # lower() dijalankan oleh PostgreSQL, sama dengan kolom name_key
    key = func.lower(name)
    reserved = db.execute(
        select(Category.id)
        .where(
            Category.user_id.is_(None),
            Category.category_type == category_type,
            Category.name_key == key,
        )
        .limit(1)
    ).first()
    if reserved is not None:
        raise CategoryNameReservedError()

    conditions = [
        Category.user_id == user_id,
        Category.category_type == category_type,
        Category.name_key == key,
    ]
    if exclude_id is not None:
        conditions.append(Category.id != exclude_id)
    taken = db.execute(select(Category.id).where(*conditions).limit(1)).first()
    if taken is not None:
        raise CategoryNameTakenError()


def list_categories(
    db: Session,
    *,
    user_id: uuid.UUID,
    category_type: CategoryType | None = None,
    scope: ScopeFilter = "all",
    status: StatusFilter = "active",
    search: str | None = None,
    sort: SortField = "name",
    order: SortOrder = "asc",
    page: int = 1,
    limit: int = 50,
) -> tuple[list[Category], int]:
    if scope == "global":
        conditions = [Category.user_id.is_(None)]
    elif scope == "personal":
        conditions = [Category.user_id == user_id]
    else:
        conditions = [
            or_(Category.user_id.is_(None), Category.user_id == user_id)
        ]
    if category_type is not None:
        conditions.append(Category.category_type == category_type.value)
    if status == "active":
        conditions.append(Category.is_active.is_(True))
    elif status == "archived":
        conditions.append(Category.is_active.is_(False))
    search = search.strip() if search else None
    if search:
        conditions.append(
            Category.name.ilike(f"%{_escape_like(search)}%", escape="\\")
        )

    total = db.execute(
        select(func.count()).select_from(Category).where(*conditions)
    ).scalar_one()

    column = SORT_COLUMNS[sort]
    ordering = column.asc() if order == "asc" else column.desc()
    rows = (
        db.execute(
            select(Category)
            .where(*conditions)
            # id sebagai penentu akhir agar halaman stabil
            .order_by(ordering, Category.id)
            .limit(limit)
            .offset((page - 1) * limit)
        )
        .scalars()
        .all()
    )
    return list(rows), total


def create_category(
    db: Session,
    *,
    user_id: uuid.UUID,
    name: str,
    category_type: CategoryType,
    icon: str | None,
    color: str | None,
    ip_address: str | None = None,
) -> Category:
    _ensure_name_available(
        db, user_id=user_id, category_type=category_type.value, name=name
    )
    category = Category(
        user_id=user_id,
        name=name,
        category_type=category_type.value,
        icon=icon,
        color=color,
    )
    try:
        db.add(category)
        db.flush()
        audit.record(
            db,
            user_id=user_id,
            action=audit.AuditAction.CATEGORY_CREATED,
            resource_type="category",
            resource_id=category.id,
            metadata={"category_type": category_type.value},
            ip_address=ip_address,
        )
        db.commit()
    except IntegrityError as exc:
        # Dua permintaan bersamaan dengan nama sama: yang kalah ditolak oleh
        # unique index database, bukan oleh pengecekan di atas.
        db.rollback()
        raise CategoryNameTakenError() from exc
    except Exception:
        db.rollback()
        raise
    db.refresh(category)
    return category


def update_category(
    db: Session,
    *,
    user_id: uuid.UUID,
    category_id: uuid.UUID,
    changes: dict[str, Any],
    ip_address: str | None = None,
) -> Category:
    category = _get_owned(db, user_id=user_id, category_id=category_id)
    if not category.is_active:
        raise CategoryArchivedError()

    changed: list[str] = []
    try:
        if "name" in changes and changes["name"] != category.name:
            _ensure_name_available(
                db,
                user_id=user_id,
                category_type=category.category_type,
                name=changes["name"],
                exclude_id=category.id,
            )
            category.name = changes["name"]
            changed.append("name")
        for field in ("icon", "color"):
            if field in changes and changes[field] != getattr(category, field):
                setattr(category, field, changes[field])
                changed.append(field)
        if changed:
            audit.record(
                db,
                user_id=user_id,
                action=audit.AuditAction.CATEGORY_UPDATED,
                resource_type="category",
                resource_id=category.id,
                metadata={"fields": changed},
                ip_address=ip_address,
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise CategoryNameTakenError() from exc
    except Exception:
        db.rollback()
        raise
    db.refresh(category)
    return category


def _set_active(
    db: Session,
    *,
    user_id: uuid.UUID,
    category_id: uuid.UUID,
    make_active: bool,
    ip_address: str | None,
) -> Category:
    category = _get_owned(db, user_id=user_id, category_id=category_id)
    if make_active:
        if category.is_active:
            raise CategoryNotArchivedError()
        action = audit.AuditAction.CATEGORY_UNARCHIVED
    else:
        if not category.is_active:
            raise CategoryAlreadyArchivedError()
        action = audit.AuditAction.CATEGORY_ARCHIVED
    try:
        category.is_active = make_active
        audit.record(
            db,
            user_id=user_id,
            action=action,
            resource_type="category",
            resource_id=category.id,
            ip_address=ip_address,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(category)
    return category


def archive_category(
    db: Session,
    *,
    user_id: uuid.UUID,
    category_id: uuid.UUID,
    ip_address: str | None = None,
) -> Category:
    return _set_active(
        db,
        user_id=user_id,
        category_id=category_id,
        make_active=False,
        ip_address=ip_address,
    )


def unarchive_category(
    db: Session,
    *,
    user_id: uuid.UUID,
    category_id: uuid.UUID,
    ip_address: str | None = None,
) -> Category:
    return _set_active(
        db,
        user_id=user_id,
        category_id=category_id,
        make_active=True,
        ip_address=ip_address,
    )
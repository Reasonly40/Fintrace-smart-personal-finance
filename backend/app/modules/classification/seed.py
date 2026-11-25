from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.modules.classification.enums import CategoryType
from app.modules.classification.models import Category

EXPENSE = CategoryType.EXPENSE
INCOME = CategoryType.INCOME


@dataclass(frozen=True)
class SeedCategory:
    name: str
    category_type: CategoryType
    icon: str
    color: str


# Daftar yang disetujui di keputusan 4. Migration data memegang salinan beku
# yang sama; tes memastikan keduanya tidak menyimpang.
GLOBAL_CATEGORIES: tuple[SeedCategory, ...] = (
    SeedCategory("Makanan & Minuman", EXPENSE, "utensils", "#F97316"),
    SeedCategory("Transportasi", EXPENSE, "car", "#3B82F6"),
    SeedCategory("Belanja", EXPENSE, "shopping-bag", "#EC4899"),
    SeedCategory("Tagihan & Utilitas", EXPENSE, "receipt", "#EAB308"),
    SeedCategory("Kesehatan", EXPENSE, "heart-pulse", "#EF4444"),
    SeedCategory("Pendidikan", EXPENSE, "graduation-cap", "#8B5CF6"),
    SeedCategory("Hiburan", EXPENSE, "clapperboard", "#14B8A6"),
    SeedCategory("Rumah Tangga", EXPENSE, "house", "#A16207"),
    SeedCategory("Donasi & Sosial", EXPENSE, "hand-heart", "#F43F5E"),
    SeedCategory("Lainnya", EXPENSE, "ellipsis", "#6B7280"),
    SeedCategory("Gaji", INCOME, "wallet", "#16A34A"),
    SeedCategory("Bonus", INCOME, "gift", "#22C55E"),
    SeedCategory("Usaha", INCOME, "store", "#0EA5E9"),
    SeedCategory("Investasi", INCOME, "trending-up", "#6366F1"),
    SeedCategory("Hadiah", INCOME, "party-popper", "#84CC16"),
    SeedCategory("Lainnya", INCOME, "ellipsis", "#6B7280"),
)


def ensure_global_categories(db: Session) -> None:
    """Pastikan semua kategori bawaan ada. Idempotent; tanpa commit.

    Dipakai tes untuk memulihkan data bawaan setelah pengosongan database.
    Di lingkungan nyata data bawaan datang dari migration."""
    for item in GLOBAL_CATEGORIES:
        db.execute(
            pg_insert(Category)
            .values(
                name=item.name,
                category_type=item.category_type.value,
                icon=item.icon,
                color=item.color,
            )
            .on_conflict_do_nothing(
                index_elements=["category_type", "name_key"],
                index_where=text("user_id IS NULL"),
            )
        )
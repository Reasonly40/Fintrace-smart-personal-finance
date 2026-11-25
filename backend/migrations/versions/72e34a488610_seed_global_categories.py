"""seed global categories

Revision ID: 72e34a488610
Revises: 926f33a35576
Create Date: 2026-11-25 20:58:13.977526

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '72e34a488610'
down_revision: Union[str, Sequence[str], None] = '926f33a35576'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Salinan beku daftar kategori bawaan saat migration ini ditulis.
# Jangan impor dari kode aplikasi: migration lama tidak boleh berubah
# perilakunya ketika daftar di aplikasi berubah.
SEED_CATEGORIES = (
    ("Makanan & Minuman", "EXPENSE", "utensils", "#F97316"),
    ("Transportasi", "EXPENSE", "car", "#3B82F6"),
    ("Belanja", "EXPENSE", "shopping-bag", "#EC4899"),
    ("Tagihan & Utilitas", "EXPENSE", "receipt", "#EAB308"),
    ("Kesehatan", "EXPENSE", "heart-pulse", "#EF4444"),
    ("Pendidikan", "EXPENSE", "graduation-cap", "#8B5CF6"),
    ("Hiburan", "EXPENSE", "clapperboard", "#14B8A6"),
    ("Rumah Tangga", "EXPENSE", "house", "#A16207"),
    ("Donasi & Sosial", "EXPENSE", "hand-heart", "#F43F5E"),
    ("Lainnya", "EXPENSE", "ellipsis", "#6B7280"),
    ("Gaji", "INCOME", "wallet", "#16A34A"),
    ("Bonus", "INCOME", "gift", "#22C55E"),
    ("Usaha", "INCOME", "store", "#0EA5E9"),
    ("Investasi", "INCOME", "trending-up", "#6366F1"),
    ("Hadiah", "INCOME", "party-popper", "#84CC16"),
    ("Lainnya", "INCOME", "ellipsis", "#6B7280"),
)

INSERT_CATEGORY = """
INSERT INTO categories (name, category_type, icon, color)
VALUES (:name, :category_type, :icon, :color)
ON CONFLICT (category_type, name_key) WHERE user_id IS NULL DO NOTHING
"""

DELETE_CATEGORY = """
DELETE FROM categories
WHERE user_id IS NULL AND category_type = :category_type AND name = :name
"""

def upgrade() -> None:
    """Upgrade schema."""
    connection = op.get_bind()
    for name, category_type, icon, color in SEED_CATEGORIES:
        connection.execute(
            sa.text(INSERT_CATEGORY),
            {
                "name": name,
                "category_type": category_type,
                "icon": icon,
                "color": color,
            },
        )


def downgrade() -> None:
    """Downgrade schema."""
    connection = op.get_bind()
    for name, category_type, _icon, _color in SEED_CATEGORIES:
        connection.execute(
            sa.text(DELETE_CATEGORY),
            {"name": name, "category_type": category_type},
        )

"""add users timezone check constraint

Revision ID: 00c2cb8e1135
Revises: 609a6bedfa6f
Create Date: 2026-11-24 15:32:32.500146

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '00c2cb8e1135'
down_revision: Union[str, Sequence[str], None] = '609a6bedfa6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_check_constraint(
        op.f("ck_users_timezone_not_blank"),
        "users",
        "length(btrim(timezone)) > 0",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("ck_users_timezone_not_blank"), "users", type_="check"
    )

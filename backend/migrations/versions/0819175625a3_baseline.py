"""baseline

Revision ID: 0819175625a3
Revises: 3e91f396bf1f
Create Date: 2026-11-14 12:53:10.645995

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0819175625a3'
down_revision: Union[str, Sequence[str], None] = '3e91f396bf1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

"""ensure users timezone check constraint

Revision ID: 8d2fe131b6f2
Revises: a7453d0a729e
Create Date: 2026-11-24 16:43:22.546588

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8d2fe131b6f2'
down_revision: Union[str, Sequence[str], None] = 'a7453d0a729e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DROP_TIMEZONE_CHECK = """
ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_timezone_not_blank
"""

ADD_TIMEZONE_CHECK = """
ALTER TABLE users
    ADD CONSTRAINT ck_users_timezone_not_blank
    CHECK (length(btrim(timezone)) > 0)
"""

def upgrade() -> None:
    """Upgrade schema."""
    # DROP IF EXISTS membuat migration aman walau constraint ternyata sudah
    # ada di database pengembangan Anda.
    op.execute(DROP_TIMEZONE_CHECK)
    op.execute(ADD_TIMEZONE_CHECK)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(DROP_TIMEZONE_CHECK)

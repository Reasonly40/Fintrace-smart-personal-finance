"""make audit logs append only

Revision ID: a7453d0a729e
Revises: fa61e7d92620
Create Date: 2026-11-24 15:53:16.968583

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7453d0a729e'
down_revision: Union[str, Sequence[str], None] = 'fa61e7d92620'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


FORBID_AUDIT_CHANGE = """
CREATE FUNCTION forbid_audit_log_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit logs are append only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql
"""

TRIGGER_AUDIT_IMMUTABLE = """
CREATE TRIGGER trg_audit_logs_immutable
BEFORE UPDATE OR DELETE ON audit_logs
FOR EACH ROW EXECUTE FUNCTION forbid_audit_log_change()
"""

def upgrade() -> None:
    """Upgrade schema."""
    op.execute(FORBID_AUDIT_CHANGE)
    op.execute(TRIGGER_AUDIT_IMMUTABLE)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER trg_audit_logs_immutable ON audit_logs")
    op.execute("DROP FUNCTION forbid_audit_log_change()")
"""fix transaction rules to read current row

Revision ID: 5ec6898e6741
Revises: 66bf54ecd3cb
Create Date: 2026-11-23 09:04:41.169467

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5ec6898e6741'
down_revision: Union[str, Sequence[str], None] = '66bf54ecd3cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


FIXED_TRANSACTION_RULES = """
CREATE OR REPLACE FUNCTION enforce_transaction_journal_rules()
RETURNS trigger AS $$
DECLARE
    cur_status text;
    cur_type text;
    cur_reversal_of uuid;
    entry_count integer;
BEGIN
    SELECT status, transaction_type, reversal_of_id
      INTO cur_status, cur_type, cur_reversal_of
      FROM transactions
     WHERE id = NEW.id;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    SELECT COUNT(*) INTO entry_count
      FROM ledger_entries
     WHERE transaction_id = NEW.id;

    IF cur_status = 'DRAFT' AND entry_count > 0 THEN
        RAISE EXCEPTION 'draft transaction must not have ledger entries'
            USING ERRCODE = '23514';
    END IF;

    IF cur_status IN ('POSTED', 'REVERSED') AND entry_count = 0 THEN
        RAISE EXCEPTION 'posted transaction must have ledger entries'
            USING ERRCODE = '23514';
    END IF;

    IF cur_status = 'REVERSED' AND NOT EXISTS (
        SELECT 1 FROM transactions WHERE reversal_of_id = NEW.id
    ) THEN
        RAISE EXCEPTION 'reversed transaction must have a reversal journal'
            USING ERRCODE = '23514';
    END IF;

    IF cur_type = 'REVERSAL' AND NOT EXISTS (
        SELECT 1 FROM transactions
         WHERE id = cur_reversal_of AND status = 'REVERSED'
    ) THEN
        RAISE EXCEPTION 'reversal must point to a reversed transaction'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
"""

PREVIOUS_TRANSACTION_RULES = """
CREATE OR REPLACE FUNCTION enforce_transaction_journal_rules()
RETURNS trigger AS $$
DECLARE
    entry_count integer;
BEGIN
    SELECT COUNT(*) INTO entry_count
      FROM ledger_entries
     WHERE transaction_id = NEW.id;

    IF NEW.status = 'DRAFT' AND entry_count > 0 THEN
        RAISE EXCEPTION 'draft transaction must not have ledger entries'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.status IN ('POSTED', 'REVERSED') AND entry_count = 0 THEN
        RAISE EXCEPTION 'posted transaction must have ledger entries'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.status = 'REVERSED' AND NOT EXISTS (
        SELECT 1 FROM transactions WHERE reversal_of_id = NEW.id
    ) THEN
        RAISE EXCEPTION 'reversed transaction must have a reversal journal'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.transaction_type = 'REVERSAL' AND NOT EXISTS (
        SELECT 1 FROM transactions
         WHERE id = NEW.reversal_of_id AND status = 'REVERSED'
    ) THEN
        RAISE EXCEPTION 'reversal must point to a reversed transaction'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
"""

def upgrade() -> None:
    """Upgrade schema."""
    op.execute(FIXED_TRANSACTION_RULES)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(PREVIOUS_TRANSACTION_RULES)
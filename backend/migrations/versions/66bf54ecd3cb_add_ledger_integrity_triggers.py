"""add ledger integrity triggers

Revision ID: 66bf54ecd3cb
Revises: cb8281099946
Create Date: 2026-11-23 08:53:18.388129

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '66bf54ecd3cb'
down_revision: Union[str, Sequence[str], None] = 'cb8281099946'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENFORCE_JOURNAL_BALANCED = """
CREATE FUNCTION enforce_journal_balanced() RETURNS trigger AS $$
DECLARE
    debit_total numeric;
    credit_total numeric;
    header_amount numeric;
BEGIN
    SELECT COALESCE(SUM(amount) FILTER (WHERE entry_type = 'DEBIT'), 0),
           COALESCE(SUM(amount) FILTER (WHERE entry_type = 'CREDIT'), 0)
      INTO debit_total, credit_total
      FROM ledger_entries
     WHERE transaction_id = NEW.transaction_id;

    SELECT amount INTO header_amount
      FROM transactions
     WHERE id = NEW.transaction_id;

    IF debit_total <> credit_total OR debit_total <> header_amount THEN
        RAISE EXCEPTION 'journal must balance and match the transaction amount'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
"""

TRIGGER_JOURNAL_BALANCED = """
CREATE CONSTRAINT TRIGGER trg_ledger_entries_balanced
AFTER INSERT ON ledger_entries
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_journal_balanced()
"""

ENFORCE_TRANSACTION_RULES = """
CREATE FUNCTION enforce_transaction_journal_rules() RETURNS trigger AS $$
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

TRIGGER_TRANSACTION_RULES = """
CREATE CONSTRAINT TRIGGER trg_transactions_journal_rules
AFTER INSERT OR UPDATE OF status ON transactions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_transaction_journal_rules()
"""

PROTECT_POSTED_TRANSACTIONS = """
CREATE FUNCTION protect_posted_transactions() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'DRAFT' THEN
            RAISE EXCEPTION 'posted transactions cannot be deleted'
                USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.status = 'DRAFT' THEN
        IF NEW.status NOT IN ('DRAFT', 'POSTED') THEN
            RAISE EXCEPTION 'a draft can only become posted'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status = 'POSTED' AND NEW.status = 'REVERSED'
       AND (to_jsonb(NEW) - 'status' - 'updated_at')
         = (to_jsonb(OLD) - 'status' - 'updated_at') THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'posted transactions are immutable'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql
"""

TRIGGER_PROTECT_POSTED = """
CREATE TRIGGER trg_transactions_protect_posted
BEFORE UPDATE OR DELETE ON transactions
FOR EACH ROW EXECUTE FUNCTION protect_posted_transactions()
"""

FORBID_ENTRY_CHANGE = """
CREATE FUNCTION forbid_ledger_entry_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'ledger entries are immutable' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql
"""

TRIGGER_ENTRIES_IMMUTABLE = """
CREATE TRIGGER trg_ledger_entries_immutable
BEFORE UPDATE OR DELETE ON ledger_entries
FOR EACH ROW EXECUTE FUNCTION forbid_ledger_entry_change()
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(ENFORCE_JOURNAL_BALANCED)
    op.execute(TRIGGER_JOURNAL_BALANCED)
    op.execute(ENFORCE_TRANSACTION_RULES)
    op.execute(TRIGGER_TRANSACTION_RULES)
    op.execute(PROTECT_POSTED_TRANSACTIONS)
    op.execute(TRIGGER_PROTECT_POSTED)
    op.execute(FORBID_ENTRY_CHANGE)
    op.execute(TRIGGER_ENTRIES_IMMUTABLE)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER trg_ledger_entries_immutable ON ledger_entries")
    op.execute("DROP TRIGGER trg_transactions_protect_posted ON transactions")
    op.execute("DROP TRIGGER trg_transactions_journal_rules ON transactions")
    op.execute("DROP TRIGGER trg_ledger_entries_balanced ON ledger_entries")
    op.execute("DROP FUNCTION forbid_ledger_entry_change()")
    op.execute("DROP FUNCTION protect_posted_transactions()")
    op.execute("DROP FUNCTION enforce_transaction_journal_rules()")
    op.execute("DROP FUNCTION enforce_journal_balanced()")

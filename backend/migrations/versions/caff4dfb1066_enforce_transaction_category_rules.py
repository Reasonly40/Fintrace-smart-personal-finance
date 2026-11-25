"""enforce transaction category rules

Revision ID: caff4dfb1066
Revises: 06f17662319a
Create Date: 2026-11-25 21:49:29.155971

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'caff4dfb1066'
down_revision: Union[str, Sequence[str], None] = '06f17662319a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DROP_CATEGORY_CHECK = """
ALTER TABLE transactions
    DROP CONSTRAINT IF EXISTS ck_transactions_category_only_income_expense
"""

ADD_CATEGORY_CHECK = """
ALTER TABLE transactions
    ADD CONSTRAINT ck_transactions_category_only_income_expense
    CHECK (category_id IS NULL OR transaction_type IN ('INCOME', 'EXPENSE'))
"""

ENFORCE_CATEGORY = """
CREATE FUNCTION enforce_transaction_category() RETURNS trigger AS $$
DECLARE
    cat_user uuid;
    cat_type text;
    cat_active boolean;
BEGIN
    IF NEW.category_id IS NULL THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF NEW.category_id IS NOT DISTINCT FROM OLD.category_id THEN
            RETURN NEW;
        END IF;
    END IF;

    SELECT user_id, category_type, is_active
      INTO cat_user, cat_type, cat_active
      FROM categories
     WHERE id = NEW.category_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'category does not exist' USING ERRCODE = '23503';
    END IF;
    IF cat_user IS NOT NULL AND cat_user <> NEW.user_id THEN
        RAISE EXCEPTION 'category belongs to another user'
            USING ERRCODE = '23514';
    END IF;
    IF cat_type <> NEW.transaction_type THEN
        RAISE EXCEPTION 'category type must match the transaction type'
            USING ERRCODE = '23514';
    END IF;
    IF NOT cat_active THEN
        RAISE EXCEPTION 'archived categories cannot be newly assigned'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

TRIGGER_CATEGORY = """
CREATE TRIGGER trg_transactions_category
BEFORE INSERT OR UPDATE OF category_id ON transactions
FOR EACH ROW EXECUTE FUNCTION enforce_transaction_category()
"""

NEW_PROTECT_POSTED = """
CREATE OR REPLACE FUNCTION protect_posted_transactions() RETURNS trigger AS $$
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

    -- Jalur terkontrol: transaksi POSTED non-reversal boleh berganti
    -- kategori dan deskripsi. Kolom lain tetap terkunci.
    IF OLD.status = 'POSTED' AND NEW.status = 'POSTED'
       AND OLD.transaction_type <> 'REVERSAL'
       AND (to_jsonb(NEW) - 'category_id' - 'description' - 'updated_at')
         = (to_jsonb(OLD) - 'category_id' - 'description' - 'updated_at') THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'posted transactions are immutable'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql
"""

OLD_PROTECT_POSTED = """
CREATE OR REPLACE FUNCTION protect_posted_transactions() RETURNS trigger AS $$
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


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(DROP_CATEGORY_CHECK)
    op.execute(ADD_CATEGORY_CHECK)
    op.execute(ENFORCE_CATEGORY)
    op.execute(TRIGGER_CATEGORY)
    op.execute(NEW_PROTECT_POSTED)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(OLD_PROTECT_POSTED)
    op.execute("DROP TRIGGER trg_transactions_category ON transactions")
    op.execute("DROP FUNCTION enforce_transaction_category()")
    op.execute(DROP_CATEGORY_CHECK)

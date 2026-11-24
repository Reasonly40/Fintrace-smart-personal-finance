from datetime import UTC, datetime

from app.modules.financial_core import service as ledger_service


def make_draft(db, user, kind, amount, wallet=None, source=None, target=None):
    """Buat draft dan commit, supaya tidak ikut batal bila ada rollback."""
    tx = ledger_service.create_draft(
        db,
        user_id=user.id,
        transaction_type=kind,
        amount=amount,
        wallet_id=wallet.id if wallet else None,
        from_wallet_id=source.id if source else None,
        to_wallet_id=target.id if target else None,
        occurred_at=datetime.now(UTC),
    )
    db.commit()
    return tx


def post_new(db, user, kind, amount, **wallets):
    tx = make_draft(db, user, kind, amount, **wallets)
    ledger_service.post_transaction(db, user_id=user.id, transaction_id=tx.id)
    db.commit()
    return tx


def reverse_existing(db, user, tx, reason="Koreksi"):
    reversal = ledger_service.reverse_transaction(
        db, user_id=user.id, transaction_id=tx.id, reason=reason
    )
    db.commit()
    return reversal
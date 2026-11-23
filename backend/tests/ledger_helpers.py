from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.modules.financial_core.models import (
    LedgerAccount,
    LedgerEntry,
    Transaction,
)
from app.modules.identity.models import User
from app.modules.wallet import service as wallet_service
from app.modules.wallet.enums import WalletType
from app.modules.wallet.models import Wallet


def make_user(db, email="a@example.com") -> User:
    user = User(email=email, password_hash="hash", full_name="Nama")
    db.add(user)
    db.flush()
    return user


def make_wallet(db, user, name="BCA") -> Wallet:
    """Lewat service, jadi akun ASSET dan akun kontrol ikut terbuat."""
    return wallet_service.create_wallet(
        db, user_id=user.id, name=name, wallet_type=WalletType.BANK
    )


def asset_account(db, wallet) -> LedgerAccount:
    return db.execute(
        select(LedgerAccount).where(LedgerAccount.wallet_id == wallet.id)
    ).scalar_one()


def control_account(db, user_id, code) -> LedgerAccount:
    return db.execute(
        select(LedgerAccount).where(
            LedgerAccount.user_id == user_id,
            LedgerAccount.account_code == code,
        )
    ).scalar_one()


def build_transaction(user_id, **overrides) -> Transaction:
    values = {
        "user_id": user_id,
        "transaction_type": "INCOME",
        "amount": Decimal(100_000),
        "currency": "IDR",
        "occurred_at": datetime.now(UTC),
    }
    values.update(overrides)
    if values.get("status") in ("POSTED", "REVERSED"):
        values.setdefault("posted_at", datetime.now(UTC))
    return Transaction(**values)


def make_transaction(db, user_id, **overrides) -> Transaction:
    tx = build_transaction(user_id, **overrides)
    db.add(tx)
    db.flush()
    return tx


def add_entry(db, tx, account_id, entry_type, amount=None) -> LedgerEntry:
    entry = LedgerEntry(
        user_id=tx.user_id,
        transaction_id=tx.id,
        account_id=account_id,
        entry_type=entry_type,
        amount=tx.amount if amount is None else amount,
    )
    db.add(entry)
    db.flush()
    return entry


def post_income(db, user, wallet, amount=100_000) -> Transaction:
    """Income POSTED dengan jurnal seimbang: debit wallet, kredit Income."""
    tx = make_transaction(
        db,
        user.id,
        transaction_type="INCOME",
        wallet_id=wallet.id,
        amount=Decimal(amount),
        status="POSTED",
    )
    add_entry(db, tx, asset_account(db, wallet).id, "DEBIT")
    add_entry(db, tx, control_account(db, user.id, "INCOME_CONTROL").id, "CREDIT")
    return tx


def reverse(db, original, *, mark_original=True) -> Transaction:
    """Reversal lengkap: transaksi REVERSAL, jurnal kebalikan, lalu
    transaksi asli ditandai REVERSED."""
    reversal = make_transaction(
        db,
        original.user_id,
        transaction_type="REVERSAL",
        status="POSTED",
        reversal_of_id=original.id,
        amount=original.amount,
    )
    entries = (
        db.execute(
            select(LedgerEntry).where(LedgerEntry.transaction_id == original.id)
        )
        .scalars()
        .all()
    )
    for entry in entries:
        flipped = "CREDIT" if entry.entry_type == "DEBIT" else "DEBIT"
        add_entry(db, reversal, entry.account_id, flipped, amount=entry.amount)
    if mark_original:
        original.status = "REVERSED"
        db.flush()
    return reversal


def validate_deferred(db) -> None:
    """Paksa pemeriksaan constraint yang ditunda, seolah-olah commit."""
    db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    db.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def expect_rejected(db, obj) -> None:
    """Objek harus ditolak database saat flush."""
    db.add(obj)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def expect_flush_rejected(db) -> None:
    """Perubahan yang sudah dibuat harus ditolak saat flush."""
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def expect_invalid_at_commit(db) -> None:
    """Pemeriksaan yang ditunda harus gagal saat 'commit'."""
    with pytest.raises(IntegrityError):
        db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    db.rollback()
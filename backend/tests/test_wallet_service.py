import pytest
from sqlalchemy import func, select, text

from app.modules.financial_core import service as ledger_service
from app.modules.financial_core.models import LedgerAccount
from app.modules.identity.models import User
from app.modules.wallet import service as wallet_service
from app.modules.wallet.enums import WalletType
from app.modules.wallet.models import Wallet

SYSTEM_CODES = {"INCOME_CONTROL", "EXPENSE_CONTROL", "OPENING_BALANCE_EQUITY"}


def make_user(db, email="a@example.com"):
    user = User(email=email, password_hash="hash", full_name="Nama")
    db.add(user)
    db.flush()
    return user


def new_wallet(db, user, name="BCA", wallet_type=WalletType.BANK):
    return wallet_service.create_wallet(
        db, user_id=user.id, name=name, wallet_type=wallet_type
    )


def accounts_of(db, user, **filters):
    return (
        db.execute(
            select(LedgerAccount).where(
                LedgerAccount.user_id == user.id, *[
                    getattr(LedgerAccount, key) == value
                    for key, value in filters.items()
                ]
            )
        )
        .scalars()
        .all()
    )


def test_create_wallet_creates_exactly_one_asset_account(db_session):
    user = make_user(db_session)

    wallet = new_wallet(db_session, user, name="  BCA  ")

    assert wallet.name == "BCA"
    assert wallet.currency == "IDR"
    assert wallet.is_active is True

    linked = accounts_of(db_session, user, wallet_id=wallet.id)
    assert len(linked) == 1
    account = linked[0]
    assert account.account_type == "ASSET"
    assert account.normal_side == "DEBIT"
    assert account.is_system is False
    assert account.account_name == "BCA"

    # FIN-004: invariant lintas tabel lolos saat commit
    db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_first_wallet_creates_the_three_system_accounts(db_session):
    user = make_user(db_session)

    new_wallet(db_session, user)

    system = {a.account_code: a for a in accounts_of(db_session, user, is_system=True)}
    assert set(system) == SYSTEM_CODES
    assert system["INCOME_CONTROL"].account_type == "INCOME"
    assert system["INCOME_CONTROL"].normal_side == "CREDIT"
    assert system["EXPENSE_CONTROL"].account_type == "EXPENSE"
    assert system["EXPENSE_CONTROL"].normal_side == "DEBIT"
    assert system["OPENING_BALANCE_EQUITY"].account_type == "EQUITY"
    assert all(a.wallet_id is None for a in system.values())


def test_second_wallet_does_not_duplicate_system_accounts(db_session):
    user = make_user(db_session)

    new_wallet(db_session, user, name="BCA")
    new_wallet(db_session, user, name="Dana", wallet_type=WalletType.E_WALLET)

    assert len(accounts_of(db_session, user, is_system=True)) == 3
    assert len(accounts_of(db_session, user, account_type="ASSET")) == 2


def test_ensure_system_accounts_is_idempotent(db_session):
    user = make_user(db_session)

    first = ledger_service.ensure_system_accounts(db_session, user.id)
    second = ledger_service.ensure_system_accounts(db_session, user.id)

    assert set(first) == set(second) == SYSTEM_CODES
    assert {a.id for a in first.values()} == {a.id for a in second.values()}


def test_system_accounts_are_separate_per_user(db_session):
    first = make_user(db_session, "satu@example.com")
    second = make_user(db_session, "dua@example.com")

    new_wallet(db_session, first)
    new_wallet(db_session, second)

    assert len(accounts_of(db_session, first, is_system=True)) == 3
    assert len(accounts_of(db_session, second, is_system=True)) == 3
    first_ids = {a.id for a in accounts_of(db_session, first, is_system=True)}
    second_ids = {a.id for a in accounts_of(db_session, second, is_system=True)}
    assert first_ids.isdisjoint(second_ids)


def test_failure_while_creating_account_leaves_no_wallet(
    db_session, monkeypatch
):
    user = make_user(db_session)
    db_session.commit()  # user tersimpan; yang diuji hanya rollback wallet

    def boom(*args, **kwargs):
        raise RuntimeError("gagal membuat akun")

    monkeypatch.setattr(ledger_service, "create_wallet_asset_account", boom)

    with pytest.raises(RuntimeError):
        new_wallet(db_session, user)

    wallets = db_session.execute(
        select(func.count()).select_from(Wallet)
    ).scalar_one()
    assert wallets == 0
    assert db_session.get(User, user.id) is not None
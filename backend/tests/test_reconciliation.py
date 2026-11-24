import random

import pytest
from sqlalchemy import func, select

from app.modules.financial_core.balance import wallet_balances
from app.modules.financial_core.enums import TransactionType
from app.modules.financial_core.errors import InsufficientBalanceError
from app.modules.financial_core.models import LedgerAccount, LedgerEntry
from app.modules.financial_core.reconciliation import reconcile_user
from tests.flow_helpers import post_new, reverse_existing
from tests.ledger_helpers import (
    add_entry,
    asset_account,
    control_account,
    make_transaction,
    make_user,
    make_wallet,
    post_expense,
    validate_deferred,
)

INCOME = TransactionType.INCOME
EXPENSE = TransactionType.EXPENSE
OPENING = TransactionType.OPENING_BALANCE
TRANSFER = TransactionType.TRANSFER


# ---------- ledger yang sehat ----------


def test_empty_ledger_is_consistent(db_session):
    user = make_user(db_session)
    make_wallet(db_session, user)

    report = reconcile_user(db_session, user_id=user.id)

    assert report.is_consistent
    assert report.total_debit == report.total_credit == 0
    assert report.assets == report.income == report.expense == report.equity == 0


def test_accounting_equation_with_known_numbers(db_session):
    user = make_user(db_session)
    first = make_wallet(db_session, user, "Satu")
    second = make_wallet(db_session, user, "Dua")
    post_new(db_session, user, OPENING, 1_000_000, wallet=first)
    post_new(db_session, user, INCOME, 500_000, wallet=first)
    expense = post_new(db_session, user, EXPENSE, 200_000, wallet=first)
    post_new(db_session, user, TRANSFER, 100_000, source=first, target=second)
    reverse_existing(db_session, user, expense)

    report = reconcile_user(db_session, user_id=user.id)

    assert report.assets == 1_500_000
    assert report.income == 500_000
    assert report.equity == 1_000_000
    assert report.expense == 0
    assert report.balances == {first.id: 1_400_000, second.id: 100_000}
    assert report.equation_holds
    assert report.is_consistent
    validate_deferred(db_session)


def test_reversed_pairs_cancel_out_account_by_account(db_session):
    user = make_user(db_session)
    first = make_wallet(db_session, user, "Satu")
    second = make_wallet(db_session, user, "Dua")
    income = post_new(db_session, user, INCOME, 100_000, wallet=first)
    transfer = post_new(
        db_session, user, TRANSFER, 40_000, source=first, target=second
    )
    reverse_existing(db_session, user, transfer)
    reverse_existing(db_session, user, income)

    signed = func.sum(
        func.coalesce(
            func.nullif(0, 0), 0
        )
        + (
            (LedgerEntry.entry_type == "DEBIT").cast(
                db_session.bind.dialect.type_descriptor
            )
            if False
            else 0
        )
    )
    del signed  # tidak dipakai; hitungan di bawah lebih jelas
    rows = db_session.execute(
        select(LedgerAccount.id, LedgerEntry.entry_type, LedgerEntry.amount)
        .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
        .where(LedgerEntry.user_id == user.id)
    ).all()
    net = {}
    for account_id, entry_type, amount in rows:
        sign = 1 if entry_type == "DEBIT" else -1
        net[account_id] = net.get(account_id, 0) + sign * int(amount)

    assert net
    assert set(net.values()) == {0}
    report = reconcile_user(db_session, user_id=user.id)
    assert report.is_consistent
    assert report.assets == 0


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_random_activity_matches_an_independent_model(db_session, seed):
    """Aktivitas acak yang diulang dengan benih tetap. Setiap langkah
    dibandingkan dengan pembukuan sederhana di Python."""
    rng = random.Random(seed)
    user = make_user(db_session)
    wallets = [make_wallet(db_session, user, f"Wallet {i}") for i in range(3)]
    model = {wallet.id: 0 for wallet in wallets}
    income_net = 0
    expense_net = 0
    reversible = []  # (tx, jenis, nominal, wallet pertama, wallet kedua)

    for _ in range(60):
        action = rng.choice(["income", "income", "expense", "transfer", "reverse"])
        amount = rng.randrange(1, 40) * 5_000
        try:
            if action == "income":
                wallet = rng.choice(wallets)
                tx = post_new(db_session, user, INCOME, amount, wallet=wallet)
                model[wallet.id] += amount
                income_net += amount
                reversible.append((tx, "income", amount, wallet, None))
            elif action == "expense":
                wallet = rng.choice(wallets)
                tx = post_new(db_session, user, EXPENSE, amount, wallet=wallet)
                model[wallet.id] -= amount
                expense_net += amount
                reversible.append((tx, "expense", amount, wallet, None))
            elif action == "transfer":
                source, target = rng.sample(wallets, 2)
                tx = post_new(
                    db_session,
                    user,
                    TRANSFER,
                    amount,
                    source=source,
                    target=target,
                )
                model[source.id] -= amount
                model[target.id] += amount
                reversible.append((tx, "transfer", amount, source, target))
            elif reversible:
                index = rng.randrange(len(reversible))
                tx, kind, original_amount, first, second = reversible[index]
                reverse_existing(db_session, user, tx)
                reversible.pop(index)
                if kind == "income":
                    model[first.id] -= original_amount
                    income_net -= original_amount
                elif kind == "expense":
                    model[first.id] += original_amount
                    expense_net -= original_amount
                else:
                    model[first.id] += original_amount
                    model[second.id] -= original_amount
        except InsufficientBalanceError:
            continue  # penolakan sah; model tidak berubah

        actual = wallet_balances(
            db_session, user_id=user.id, wallet_ids=list(model)
        )
        assert actual == model
        assert all(balance >= 0 for balance in actual.values())

    report = reconcile_user(db_session, user_id=user.id)
    assert report.is_consistent
    assert report.assets == sum(model.values())
    assert report.income == income_net
    assert report.expense == expense_net
    assert report.equity == 0
    validate_deferred(db_session)


# ---------- pemeriksa harus bisa mendeteksi ledger yang rusak ----------


def test_checker_flags_posted_transaction_without_entries(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    tx = make_transaction(
        db_session, user.id, wallet_id=wallet.id, status="POSTED"
    )

    report = reconcile_user(db_session, user_id=user.id)

    assert report.transactions_without_entries == (tx.id,)
    assert not report.is_consistent


def test_checker_flags_unbalanced_journal(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    tx = make_transaction(
        db_session, user.id, wallet_id=wallet.id, status="POSTED"
    )
    add_entry(db_session, tx, asset_account(db_session, wallet).id, "DEBIT")
    income = control_account(db_session, user.id, "INCOME_CONTROL")
    add_entry(db_session, tx, income.id, "CREDIT", amount=90_000)

    report = reconcile_user(db_session, user_id=user.id)

    assert report.unbalanced_transactions == (tx.id,)
    assert report.total_debit != report.total_credit
    assert not report.is_consistent


def test_checker_flags_a_negative_wallet(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    post_expense(db_session, user, wallet, 30_000)  # tanpa saldo sama sekali

    report = reconcile_user(db_session, user_id=user.id)

    assert report.negative_wallets == (wallet.id,)
    assert report.balances[wallet.id] == -30_000
    assert not report.is_consistent
from app.modules.financial_core.balance import wallet_balance
from tests.ledger_helpers import (
    make_user,
    make_wallet,
    post_expense,
    post_income,
    reverse,
)


def test_new_wallet_has_zero_balance(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)

    assert wallet_balance(db_session, user_id=user.id, wallet_id=wallet.id) == 0


def test_balance_follows_the_ledger(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)

    post_income(db_session, user, wallet, 100_000)
    post_expense(db_session, user, wallet, 30_000)

    balance = wallet_balance(db_session, user_id=user.id, wallet_id=wallet.id)
    assert balance == 70_000


def test_balance_is_per_wallet(db_session):
    user = make_user(db_session)
    first = make_wallet(db_session, user, "Satu")
    second = make_wallet(db_session, user, "Dua")

    post_income(db_session, user, first, 100_000)

    assert wallet_balance(db_session, user_id=user.id, wallet_id=first.id) == 100_000
    assert wallet_balance(db_session, user_id=user.id, wallet_id=second.id) == 0


def test_reversal_neutralises_the_original(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    original = post_income(db_session, user, wallet, 100_000)

    reverse(db_session, original)

    assert wallet_balance(db_session, user_id=user.id, wallet_id=wallet.id) == 0


def test_balance_is_scoped_to_the_user(db_session):
    owner = make_user(db_session, "pemilik@example.com")
    stranger = make_user(db_session, "asing@example.com")
    wallet = make_wallet(db_session, owner)
    post_income(db_session, owner, wallet, 100_000)

    balance = wallet_balance(db_session, user_id=stranger.id, wallet_id=wallet.id)

    assert balance == 0
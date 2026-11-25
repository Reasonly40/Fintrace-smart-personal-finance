from datetime import UTC, datetime

import pytest

from tests.category_helpers import default_category_id, make_category
from tests.ledger_helpers import (
    build_transaction,
    expect_flush_rejected,
    expect_rejected,
    make_transaction,
    make_user,
    make_wallet,
    post_income,
    reverse,
)


@pytest.mark.parametrize("kind", ["INCOME", "EXPENSE"])
def test_category_can_be_assigned_when_the_type_matches(db_session, kind):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    category = make_category(db_session, user, "Kategori Uji", kind)

    tx = make_transaction(
        db_session,
        user.id,
        transaction_type=kind,
        wallet_id=wallet.id,
        category_id=category.id,
    )
    db_session.refresh(tx)

    assert tx.category_id == category.id


def test_global_category_can_be_used(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    category_id = default_category_id(db_session, "EXPENSE")

    tx = make_transaction(
        db_session,
        user.id,
        transaction_type="EXPENSE",
        wallet_id=wallet.id,
        category_id=category_id,
    )

    assert tx.category_id == category_id


@pytest.mark.parametrize(
    ("tx_kind", "category_kind"), [("INCOME", "EXPENSE"), ("EXPENSE", "INCOME")]
)
def test_category_type_must_match_the_transaction_type(
    db_session, tx_kind, category_kind
):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    category = make_category(db_session, user, "Salah Tipe", category_kind)

    expect_rejected(
        db_session,
        build_transaction(
            user.id,
            transaction_type=tx_kind,
            wallet_id=wallet.id,
            category_id=category.id,
        ),
    )


def test_category_of_another_user_is_rejected(db_session):
    me = make_user(db_session, "saya@example.com")
    other = make_user(db_session, "lain@example.com")
    wallet = make_wallet(db_session, me)
    theirs = make_category(db_session, other, "Milik Lain", "EXPENSE")

    expect_rejected(
        db_session,
        build_transaction(
            me.id,
            transaction_type="EXPENSE",
            wallet_id=wallet.id,
            category_id=theirs.id,
        ),
    )


def test_archived_category_cannot_be_newly_assigned(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    archived = make_category(
        db_session, user, "Lama", "EXPENSE", is_active=False
    )

    expect_rejected(
        db_session,
        build_transaction(
            user.id,
            transaction_type="EXPENSE",
            wallet_id=wallet.id,
            category_id=archived.id,
        ),
    )


def test_changing_to_an_archived_category_is_rejected(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    active = make_category(db_session, user, "Aktif", "EXPENSE")
    archived = make_category(
        db_session, user, "Lama", "EXPENSE", is_active=False
    )
    tx = make_transaction(
        db_session,
        user.id,
        transaction_type="EXPENSE",
        wallet_id=wallet.id,
        category_id=active.id,
    )

    tx.category_id = archived.id

    expect_flush_rejected(db_session)


def test_existing_category_survives_archiving(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    category = make_category(db_session, user, "Kopi", "EXPENSE")
    tx = make_transaction(
        db_session,
        user.id,
        transaction_type="EXPENSE",
        wallet_id=wallet.id,
        category_id=category.id,
    )

    category.is_active = False
    db_session.flush()
    tx.description = "tetap bisa diubah"
    db_session.flush()

    assert tx.category_id == category.id


@pytest.mark.parametrize("kind", ["TRANSFER", "OPENING_BALANCE"])
def test_transfer_and_opening_balance_cannot_have_a_category(db_session, kind):
    user = make_user(db_session)
    first = make_wallet(db_session, user, "Satu")
    second = make_wallet(db_session, user, "Dua")
    category = make_category(db_session, user, "Kopi", "EXPENSE")
    if kind == "TRANSFER":
        shape = {"from_wallet_id": first.id, "to_wallet_id": second.id}
    else:
        shape = {"wallet_id": first.id}

    expect_rejected(
        db_session,
        build_transaction(
            user.id, transaction_type=kind, category_id=category.id, **shape
        ),
    )


def test_reversal_cannot_have_a_category(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    original = post_income(db_session, user, wallet)
    category = make_category(db_session, user, "Gaji Uji", "INCOME")

    expect_rejected(
        db_session,
        build_transaction(
            user.id,
            transaction_type="REVERSAL",
            status="POSTED",
            reversal_of_id=original.id,
            amount=original.amount,
            category_id=category.id,
        ),
    )


@pytest.mark.parametrize("field", ["category_id", "description"])
def test_posted_transaction_allows_category_and_description_edits(
    db_session, field
):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    first = make_category(db_session, user, "Satu", "EXPENSE")
    second = make_category(db_session, user, "Dua", "EXPENSE")
    tx = make_transaction(
        db_session,
        user.id,
        transaction_type="EXPENSE",
        wallet_id=wallet.id,
        category_id=first.id,
        status="POSTED",
    )

    if field == "category_id":
        tx.category_id = second.id
        expected = second.id
    else:
        tx.description = "dikoreksi"
        expected = "dikoreksi"
    db_session.flush()

    assert getattr(tx, field) == expected


def test_reversal_reason_cannot_be_edited(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    reversal = reverse(db_session, post_income(db_session, user, wallet))

    reversal.description = "alasan ditulis ulang"

    expect_flush_rejected(db_session)


def test_reversed_transaction_category_is_frozen(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    first = make_category(db_session, user, "Satu", "INCOME")
    second = make_category(db_session, user, "Dua", "INCOME")
    income = post_income(db_session, user, wallet)
    income.category_id = first.id
    db_session.flush()
    reverse(db_session, income)

    income.category_id = second.id

    expect_flush_rejected(db_session)


def test_draft_keeps_its_category_when_posted(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    category = make_category(db_session, user, "Kopi", "EXPENSE")
    tx = make_transaction(
        db_session,
        user.id,
        transaction_type="EXPENSE",
        wallet_id=wallet.id,
        category_id=category.id,
    )

    tx.status = "POSTED"
    tx.posted_at = datetime.now(UTC)
    db_session.flush()

    assert tx.category_id == category.id


def test_category_in_use_cannot_be_deleted(db_session):
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)
    category = make_category(db_session, user, "Kopi", "EXPENSE")
    make_transaction(
        db_session,
        user.id,
        transaction_type="EXPENSE",
        wallet_id=wallet.id,
        category_id=category.id,
    )

    db_session.delete(category)

    expect_flush_rejected(db_session)


def test_expense_without_category_is_allowed_by_the_database(db_session):
    # Data lama tidak berkategori; "expense wajib kategori" ditegakkan service
    user = make_user(db_session)
    wallet = make_wallet(db_session, user)

    tx = make_transaction(
        db_session, user.id, transaction_type="EXPENSE", wallet_id=wallet.id
    )

    assert tx.category_id is None
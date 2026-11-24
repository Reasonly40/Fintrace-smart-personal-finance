import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from app.modules.financial_core import service as ledger_service
from app.modules.financial_core.balance import wallet_balance
from app.modules.financial_core.enums import TransactionType
from app.modules.financial_core.errors import (
    InsufficientBalanceError,
    TransactionAlreadyReversedError,
    TransactionNotDraftError,
    WalletNotActiveError,
)
from app.modules.financial_core.models import LedgerEntry, Transaction
from app.modules.financial_core.reconciliation import reconcile_user
from app.modules.identity.models import User
from app.modules.wallet import service as wallet_service
from app.modules.wallet.enums import WalletType
from app.modules.wallet.errors import WalletHasBalanceError
from app.modules.wallet.models import Wallet

# Tes di file ini benar-benar commit; database tes dikosongkan di sekitarnya
pytestmark = pytest.mark.concurrency

INCOME = TransactionType.INCOME
EXPENSE = TransactionType.EXPENSE
TRANSFER = TransactionType.TRANSFER


# ---------- infrastruktur ----------


@pytest.fixture
def sessions(test_engine):
    """Pabrik sesi database nyata (commit sungguhan, bukan savepoint).

    Database tes dikosongkan sebelum dan sesudah tiap tes. TRUNCATE tidak
    memicu trigger penghapusan baris, jadi ledger yang immutable tetap
    bisa dibersihkan. Aman karena fixture test_engine hanya mengizinkan
    database yang namanya mengandung 'test'."""
    factory = sessionmaker(bind=test_engine, expire_on_commit=False)

    def wipe():
        with test_engine.begin() as connection:
            connection.execute(
                text("TRUNCATE TABLE users, login_attempts CASCADE")
            )

    wipe()
    try:
        yield factory
    finally:
        wipe()


def run_parallel(tasks):
    """Jalankan semua tugas bersamaan: semuanya menunggu di barrier lalu
    mulai dalam waktu yang hampir sama. Mengembalikan daftar
    ('ok', hasil) atau ('error', pengecualian)."""
    barrier = threading.Barrier(len(tasks))

    def wrap(task):
        barrier.wait(timeout=15)
        try:
            return ("ok", task())
        except Exception as exc:
            return ("error", exc)

    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = [pool.submit(wrap, task) for task in tasks]
        return [future.result(timeout=90) for future in futures]


def oks(results):
    return [value for kind, value in results if kind == "ok"]


def errors(results):
    return [value for kind, value in results if kind == "error"]


def assert_only(results, *allowed):
    """Kegagalan boleh terjadi, tetapi hanya dari jenis yang diharapkan.
    Deadlock atau error database lain harus membuat tes gagal."""
    unexpected = [e for e in errors(results) if not isinstance(e, allowed)]
    assert unexpected == [], f"error tak terduga: {unexpected!r}"


def setup_world(factory, names=("Satu",)):
    with factory() as db:
        user = User(email="conc@example.com", password_hash="hash", full_name="N")
        db.add(user)
        db.flush()
        user_id = user.id
        wallet_ids = [
            wallet_service.create_wallet(
                db, user_id=user_id, name=name, wallet_type=WalletType.BANK
            ).id
            for name in names
        ]
    return user_id, wallet_ids


def new_draft(factory, user_id, kind, amount, **wallets):
    with factory() as db:
        tx = ledger_service.create_draft(
            db,
            user_id=user_id,
            transaction_type=kind,
            amount=amount,
            occurred_at=datetime.now(UTC),
            **wallets,
        )
        db.commit()
        return tx.id


def post_now(factory, user_id, tx_id):
    with factory() as db:
        ledger_service.post_transaction(
            db, user_id=user_id, transaction_id=tx_id
        )
        db.commit()


def seed_income(factory, user_id, wallet_id, amount):
    post_now(
        factory,
        user_id,
        new_draft(factory, user_id, INCOME, amount, wallet_id=wallet_id),
    )


def post_task(factory, user_id, tx_id):
    def task():
        post_now(factory, user_id, tx_id)

    return task


def idempotent_post_task(factory, user_id, tx_id, key):
    def task():
        with factory() as db:
            return ledger_service.post_with_idempotency(
                db,
                user_id=user_id,
                transaction_id=tx_id,
                idempotency_key=key,
            )

    return task


def reverse_task(factory, user_id, tx_id, key):
    def task():
        with factory() as db:
            return ledger_service.reverse_with_idempotency(
                db,
                user_id=user_id,
                transaction_id=tx_id,
                reason="Koreksi",
                idempotency_key=key,
            )

    return task


def balance(factory, user_id, wallet_id):
    with factory() as db:
        return wallet_balance(db, user_id=user_id, wallet_id=wallet_id)


def count(factory, model, *conditions):
    with factory() as db:
        return db.execute(
            select(func.count()).select_from(model).where(*conditions)
        ).scalar_one()


def assert_consistent(factory, user_id):
    with factory() as db:
        report = reconcile_user(db, user_id=user_id)
    assert report.is_consistent, report


# ---------- FIN-001 dan FIN-007: saldo tidak boleh negatif ----------


def test_two_expenses_cannot_overdraw_together(sessions):
    user_id, (wallet_id,) = setup_world(sessions)
    seed_income(sessions, user_id, wallet_id, 100_000)
    drafts = [
        new_draft(sessions, user_id, EXPENSE, 70_000, wallet_id=wallet_id)
        for _ in range(2)
    ]

    results = run_parallel([post_task(sessions, user_id, d) for d in drafts])

    assert len(oks(results)) == 1
    assert_only(results, InsufficientBalanceError)
    assert balance(sessions, user_id, wallet_id) == 30_000
    assert_consistent(sessions, user_id)


def test_many_expenses_never_overdraw(sessions):
    user_id, (wallet_id,) = setup_world(sessions)
    seed_income(sessions, user_id, wallet_id, 100_000)
    drafts = [
        new_draft(sessions, user_id, EXPENSE, 30_000, wallet_id=wallet_id)
        for _ in range(6)
    ]

    results = run_parallel([post_task(sessions, user_id, d) for d in drafts])

    # 3 x 30.000 muat di 100.000; yang keempat dan seterusnya tidak
    assert len(oks(results)) == 3
    assert_only(results, InsufficientBalanceError)
    assert balance(sessions, user_id, wallet_id) == 10_000
    assert_consistent(sessions, user_id)


def test_reversal_and_expense_cannot_both_spend_the_money(sessions):
    user_id, (wallet_id,) = setup_world(sessions)
    income = new_draft(sessions, user_id, INCOME, 100_000, wallet_id=wallet_id)
    post_now(sessions, user_id, income)
    expense = new_draft(
        sessions, user_id, EXPENSE, 80_000, wallet_id=wallet_id
    )

    results = run_parallel(
        [
            reverse_task(sessions, user_id, income, "reverse-key-001"),
            post_task(sessions, user_id, expense),
        ]
    )

    # Salah satu menang. Kalau expense lebih dulu, reversal income (100.000)
    # tidak muat di sisa 20.000; kalau reversal lebih dulu, expense gagal.
    assert len(oks(results)) == 1
    assert_only(results, InsufficientBalanceError)
    assert balance(sessions, user_id, wallet_id) >= 0
    assert_consistent(sessions, user_id)


# ---------- FIN-007 dan bagian 9.4: urutan kunci wallet ----------


def test_opposite_transfers_do_not_deadlock(sessions):
    user_id, (first, second) = setup_world(sessions, ("A", "B"))
    seed_income(sessions, user_id, first, 100_000)
    seed_income(sessions, user_id, second, 100_000)

    for _ in range(5):
        forward = new_draft(
            sessions,
            user_id,
            TRANSFER,
            30_000,
            from_wallet_id=first,
            to_wallet_id=second,
        )
        backward = new_draft(
            sessions,
            user_id,
            TRANSFER,
            20_000,
            from_wallet_id=second,
            to_wallet_id=first,
        )
        results = run_parallel(
            [
                post_task(sessions, user_id, forward),
                post_task(sessions, user_id, backward),
            ]
        )
        assert_only(results)  # deadlock atau error lain = gagal
        assert len(oks(results)) == 2

    # Tiap ronde: A -10.000 dan B +10.000, total tetap
    assert balance(sessions, user_id, first) == 50_000
    assert balance(sessions, user_id, second) == 150_000
    assert_consistent(sessions, user_id)


# ---------- FIN-012 dan idempotency ----------


def test_concurrent_duplicate_requests_post_once(sessions):
    user_id, (wallet_id,) = setup_world(sessions)
    tx_id = new_draft(sessions, user_id, INCOME, 100_000, wallet_id=wallet_id)

    results = run_parallel(
        [
            idempotent_post_task(sessions, user_id, tx_id, "dup-key-0001")
            for _ in range(3)
        ]
    )

    assert_only(results)
    assert sorted(result.replayed for result in oks(results)) == [
        False,
        True,
        True,
    ]
    assert count(sessions, LedgerEntry, LedgerEntry.transaction_id == tx_id) == 2
    assert balance(sessions, user_id, wallet_id) == 100_000
    assert_consistent(sessions, user_id)


def test_concurrent_posts_of_one_draft_with_different_keys(sessions):
    user_id, (wallet_id,) = setup_world(sessions)
    tx_id = new_draft(sessions, user_id, INCOME, 100_000, wallet_id=wallet_id)

    results = run_parallel(
        [
            idempotent_post_task(sessions, user_id, tx_id, f"other-key-{i:04d}")
            for i in range(4)
        ]
    )

    assert len(oks(results)) == 1
    assert_only(results, TransactionNotDraftError)
    assert count(sessions, LedgerEntry, LedgerEntry.transaction_id == tx_id) == 2
    assert balance(sessions, user_id, wallet_id) == 100_000
    assert_consistent(sessions, user_id)


# ---------- FIN-009: reversal hanya sekali ----------


def test_concurrent_reversals_reverse_once(sessions):
    user_id, (wallet_id,) = setup_world(sessions)
    income = new_draft(sessions, user_id, INCOME, 100_000, wallet_id=wallet_id)
    post_now(sessions, user_id, income)

    results = run_parallel(
        [
            reverse_task(sessions, user_id, income, f"reverse-key-{i:04d}")
            for i in range(3)
        ]
    )

    assert len(oks(results)) == 1
    assert_only(results, TransactionAlreadyReversedError)
    assert (
        count(
            sessions,
            Transaction,
            Transaction.transaction_type == "REVERSAL",
        )
        == 1
    )
    assert balance(sessions, user_id, wallet_id) == 0
    assert_consistent(sessions, user_id)


# ---------- arsip wallet melawan posting ----------


def test_archive_and_posting_never_leave_money_in_an_archived_wallet(sessions):
    user_id, (wallet_id,) = setup_world(sessions)
    income = new_draft(sessions, user_id, INCOME, 50_000, wallet_id=wallet_id)

    def archive():
        with sessions() as db:
            return wallet_service.archive_wallet(
                db, user_id=user_id, wallet_id=wallet_id
            )

    results = run_parallel([archive, post_task(sessions, user_id, income)])

    assert len(oks(results)) == 1
    assert_only(results, WalletNotActiveError, WalletHasBalanceError)
    with sessions() as db:
        active = db.execute(
            select(Wallet.is_active).where(Wallet.id == wallet_id)
        ).scalar_one()
    final_balance = balance(sessions, user_id, wallet_id)
    assert active or final_balance == 0
    assert_consistent(sessions, user_id)


# ---------- bukti bahwa lock benar-benar dipakai ----------


def test_posting_waits_for_the_wallet_lock(sessions):
    user_id, (wallet_id,) = setup_world(sessions)
    tx_id = new_draft(sessions, user_id, INCOME, 10_000, wallet_id=wallet_id)
    finished = threading.Event()
    failures = []

    def poster():
        try:
            post_now(sessions, user_id, tx_id)
        except Exception as exc:
            failures.append(exc)
        finally:
            finished.set()

    holder = sessions()
    try:
        # Sesi lain memegang lock wallet dan belum melepasnya
        ledger_service._lock_wallets(
            holder, user_id=user_id, wallet_ids=[wallet_id]
        )
        thread = threading.Thread(target=poster)
        thread.start()

        assert not finished.wait(timeout=1.0), "posting tidak menunggu lock"
        holder.rollback()  # lepas lock
        assert finished.wait(timeout=15), "posting tidak lanjut setelah lock lepas"
        thread.join(timeout=15)
    finally:
        holder.close()

    assert failures == []
    assert balance(sessions, user_id, wallet_id) == 10_000
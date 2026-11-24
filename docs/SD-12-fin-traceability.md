# Keterlacakan Invariant Keuangan (FIN-001 sampai FIN-012) ke Tes

Status per akhir Fase 2. Lapisan: **DB** (constraint/trigger), **Service**,
**API**, **Konkurensi** (sesi database paralel), **Rekonsiliasi**.

| ID | Invariant | Mekanisme | Tes utama |
|---|---|---|---|
| FIN-001 | Saldo wallet tidak boleh negatif | Row lock + validasi saldo | Service: `test_expense_above_the_balance_is_rejected`, `test_expense_equal_to_the_balance_is_allowed`, `test_reversing_income_already_spent_is_rejected`. API: `test_expense_above_the_balance_is_rejected`. Konkurensi: `test_two_expenses_cannot_overdraw_together`, `test_many_expenses_never_overdraw`, `test_reversal_and_expense_cannot_both_spend_the_money`, `test_posting_waits_for_the_wallet_lock`. Rekonsiliasi: `test_random_activity_matches_an_independent_model`, `test_checker_flags_a_negative_wallet` |
| FIN-002 | Transaksi POSTED punya ledger entries | Deferred trigger | DB: `test_posted_transaction_without_entries_is_rejected`, `test_draft_with_entries_is_rejected`, `test_draft_without_entries_is_fine`. Rekonsiliasi: `test_checker_flags_posted_transaction_without_entries` |
| FIN-003 | Total debit sama dengan total kredit | Deferred trigger | DB: `test_unbalanced_journal_is_rejected`, `test_journal_total_must_match_the_header_amount`, `test_one_sided_journal_is_rejected`, `test_balanced_journal_passes_the_commit_check`. Unit: `test_every_supported_journal_is_balanced`, `test_unbalanced_lines_are_detected`. Rekonsiliasi: `test_checker_flags_unbalanced_journal` |
| FIN-004 | Tiap wallet punya tepat satu akun ASSET | UNIQUE + deferred trigger + pembuatan atomik | DB: `test_wallet_can_have_only_one_asset_account`, `test_wallet_without_asset_account_fails_at_commit_time`. Service: `test_create_wallet_creates_exactly_one_asset_account`, `test_failure_while_creating_account_leaves_no_wallet` |
| FIN-005 | User hanya mengakses wallet miliknya | Query ter-scope + composite FK | DB: `test_account_cannot_point_to_another_users_wallet`, `test_transaction_cannot_use_another_users_wallet`, `test_entry_cannot_use_another_users_account`, `test_entry_cannot_use_another_users_transaction`, `test_reversal_cannot_point_to_another_users_transaction`. API (IDOR): `test_idor_sessions.py`, `test_idor_wallets.py`, `test_idor_transactions.py`, `test_idor_transfers.py`, `test_idor_reversals.py` |
| FIN-006 | Transfer tidak boleh memakai wallet sama | CHECK + validasi schema dan service | DB: `test_transfer_to_the_same_wallet_is_rejected` (`test_transaction_models.py`). Service: `test_transfer_to_the_same_wallet_is_rejected` (`test_transfer_service.py`). API: `test_create_rejects_wrong_wallet_fields` |
| FIN-007 | Transfer tidak boleh melebihi saldo sumber | Lock dua wallet berurutan + validasi saldo | Service: `test_transfer_above_the_source_balance_is_rejected`, `test_transfer_equal_to_the_source_balance_is_allowed`. API: `test_transfer_above_the_source_balance_is_rejected`. Konkurensi: `test_opposite_transfers_do_not_deadlock` |
| FIN-008 | Transaksi posted tidak dapat diedit langsung | Trigger BEFORE UPDATE/DELETE | DB: `test_posted_transaction_cannot_be_edited`, `test_posted_transaction_cannot_be_deleted`, `test_reversing_cannot_smuggle_in_other_changes`, `test_reversed_transaction_is_final`, `test_ledger_entry_cannot_be_updated`, `test_ledger_entry_cannot_be_deleted` |
| FIN-009 | Transaksi reversed punya reversal journal | Reversal terkontrol + UNIQUE + deferred trigger | DB: `test_reversed_transaction_without_reversal_journal_is_rejected`, `test_reversal_of_a_transaction_not_marked_reversed_is_rejected`, `test_complete_reversal_passes_the_commit_check`. Service: `test_reversing_income_neutralises_it_and_keeps_history`, `test_a_transaction_can_be_reversed_only_once`. Konkurensi: `test_concurrent_reversals_reverse_once`. Rekonsiliasi: `test_reversed_pairs_cancel_out_account_by_account` |
| FIN-010 | IDR whole rupiah eksak | NUMERIC(20,0), CHECK currency, nominal integer ketat | DB: `test_transaction_amount_must_be_positive`, `test_transaction_currency_must_be_idr`, `test_wallet_currency_must_be_idr`. Unit: `test_invalid_rupiah_is_rejected`. API: `test_create_rejects_invalid_amounts` |
| FIN-011 | Kategori tidak boleh milik user lain | Belum diimplementasikan | **Menunggu modul kategori (Fase 3)** |
| FIN-012 | Header, jurnal, status, idempotency commit atomik | Satu transaksi PostgreSQL | Service: `test_a_failed_posting_does_not_burn_the_key`, `test_failed_reversal_does_not_burn_the_key`. Konkurensi: `test_concurrent_duplicate_requests_post_once`, `test_concurrent_posts_of_one_draft_with_different_keys` |

## Keterbatasan yang diketahui

- FIN-011 belum ada karena modul kategori belum dibangun.
- Tes konkurensi memeriksa invariant hasil akhir pada PostgreSQL asli,
  tetapi tidak membuktikan ketiadaan segala jenis balapan.
- Pembersihan record idempotency kedaluwarsa dan audit trail dijadwalkan
  di fase hardening.
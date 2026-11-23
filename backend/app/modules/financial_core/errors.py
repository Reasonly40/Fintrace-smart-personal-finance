from app.core.errors import AppError, ConflictError, NotFoundError


class TransactionNotFoundError(NotFoundError):
    code = "transaction_not_found"
    message = "Transaksi tidak ditemukan."


class TransactionNotDraftError(ConflictError):
    code = "transaction_not_draft"
    message = "Hanya transaksi DRAFT yang bisa diposting."


class WalletNotActiveError(ConflictError):
    code = "wallet_not_active"
    message = "Wallet tidak aktif dan tidak menerima transaksi."


class InsufficientBalanceError(ConflictError):
    code = "insufficient_balance"
    message = "Saldo wallet tidak cukup."


class OpeningBalanceNotAllowedError(ConflictError):
    code = "opening_balance_not_allowed"
    message = "Saldo awal hanya boleh dicatat saat wallet baru diinisialisasi."


class UnsupportedTransactionTypeError(AppError):
    status_code = 422
    code = "unsupported_transaction_type"
    message = "Tipe transaksi ini belum didukung."


class InvalidAmountError(AppError):
    status_code = 422
    code = "invalid_amount"
    message = "Nominal harus bilangan bulat positif."


class JournalError(AppError):
    """Pelanggaran invariant jurnal; berarti ada bug, bukan salah input."""

    status_code = 500
    code = "journal_error"
    message = "Jurnal tidak valid."

class InvalidDateRangeError(AppError):
    status_code = 422
    code = "invalid_date_range"
    message = "Rentang waktu tidak valid."

class SameWalletTransferError(AppError):
    status_code = 422
    code = "transfer_same_wallet"
    message = "Wallet asal dan tujuan transfer tidak boleh sama."


class InvalidTransactionShapeError(AppError):
    status_code = 422
    code = "invalid_wallet_fields"
    message = (
        "Kombinasi wallet_id, from_wallet_id, dan to_wallet_id tidak sesuai "
        "dengan tipe transaksi."
    )
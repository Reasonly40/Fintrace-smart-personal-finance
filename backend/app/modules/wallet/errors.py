from app.core.errors import ConflictError, NotFoundError


class WalletNotFoundError(NotFoundError):
    code = "wallet_not_found"
    message = "Wallet tidak ditemukan."


class WalletArchivedError(ConflictError):
    code = "wallet_archived"
    message = "Wallet sudah diarsipkan dan tidak bisa diubah."


class WalletAlreadyArchivedError(ConflictError):
    code = "wallet_already_archived"
    message = "Wallet sudah diarsipkan."
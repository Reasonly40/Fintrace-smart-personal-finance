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

class WalletHasBalanceError(ConflictError):
    code = "wallet_has_balance"
    message = (
        "Wallet yang masih memiliki saldo tidak bisa diarsipkan. "
        "Pindahkan atau gunakan saldonya terlebih dahulu."
    )
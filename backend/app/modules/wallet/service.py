import uuid

from sqlalchemy.orm import Session

from app.modules.financial_core import service as ledger_service
from app.modules.wallet.enums import WalletType
from app.modules.wallet.models import Wallet


def create_wallet(
    db: Session, *, user_id: uuid.UUID, name: str, wallet_type: WalletType
) -> Wallet:
    """Buat wallet beserta akun ASSET-nya dalam satu transaksi database.

    Gagal di mana pun berarti tidak ada yang tersimpan (FIN-004, FIN-012).
    """
    wallet = Wallet(
        user_id=user_id, name=name.strip(), wallet_type=wallet_type.value
    )
    try:
        db.add(wallet)
        db.flush()
        ledger_service.create_wallet_asset_account(
            db,
            user_id=user_id,
            wallet_id=wallet.id,
            name=wallet.name,
            currency=wallet.currency,
        )
        ledger_service.ensure_system_accounts(db, user_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(wallet)
    return wallet
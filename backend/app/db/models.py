"""Registri model: import semua modul model agar terdaftar di Base.metadata."""

from app.modules.financial_core import models as financial_core_models  # noqa: F401
from app.modules.identity import models as identity_models  # noqa: F401
from app.modules.operations import models as operations_models  # noqa: F401
from app.modules.wallet import models as wallet_models  # noqa: F401
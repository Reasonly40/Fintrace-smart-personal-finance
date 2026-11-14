from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db

app = FastAPI(title="Fintrace API", version="0.1.0")

DbSession = Annotated[Session, Depends(get_db)]


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness: aplikasi hidup."""
    return {"status": "ok", "env": settings.app_env}


@app.get("/health/ready")
def ready(db: DbSession) -> dict[str, str]:
    """Readiness: aplikasi siap, termasuk koneksi database."""
    try:
        db.execute(text("select 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503, detail="database unavailable"
        ) from exc
    return {"status": "ready", "database": "ok"}
from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.deps import DbSession
from app.core.errors import register_error_handlers
from app.modules.identity.router import router as auth_router

app = FastAPI(title="Fintrace API", version="0.1.0")
register_error_handlers(app)
app.include_router(auth_router, prefix="/api/v1")


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
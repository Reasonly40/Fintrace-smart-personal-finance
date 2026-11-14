from fastapi import FastAPI

from app.core.config import settings

app = FastAPI(title="Fintrace API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check: aplikasi hidup. Pengecekan database ditambah di 0.4."""
    return {"status": "ok", "env": settings.app_env}
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.main import app

BACKEND_DIR = Path(__file__).resolve().parents[1]


def run_migrations(url: str) -> None:
    """Terapkan semua migration ke database tes."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["url"] = url
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def test_engine():
    url = settings.test_database_url
    db_name = url.rsplit("/", 1)[-1] if url else ""
    # Pengaman: tes tidak boleh jalan di database yang bukan database tes
    if "test" not in db_name:
        pytest.exit(
            "TEST_DATABASE_URL harus menunjuk ke database yang namanya "
            "mengandung 'test'",
            returncode=2,
        )
    run_migrations(url)
    engine = create_engine(url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(test_engine):
    """Setiap tes berjalan dalam transaksi yang di-rollback di akhir,
    jadi data antar tes tidak saling bocor."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def second_client(client):
    """Klien kedua (pengguna lain) dengan cookie jar terpisah,
    memakai sesi database yang sama dengan `client`."""
    with TestClient(app) as c:
        yield c
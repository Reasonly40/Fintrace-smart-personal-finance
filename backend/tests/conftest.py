import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.main import app


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
from sqlalchemy import text


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_checks_database(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}


def test_session_uses_test_database(db_session):
    name = db_session.execute(text("select current_database()")).scalar()
    assert "test" in name
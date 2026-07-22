from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app


def test_health():
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}


def test_dimensions_include_suppliers(db):
    from app.simulator.engine import DigitalTwinSimulator

    DigitalTwinSimulator(db, seed=42).seed_master_data()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.get("/dimensions")
        assert response.status_code == 200
        payload = response.json()
        assert len(payload["warehouses"]) == 3
        assert len(payload["suppliers"]) == 5
        assert len(payload["skus"]) == 30
    finally:
        app.dependency_overrides.clear()


def test_simulation_endpoint_accepts_seed_and_start_date(db):
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post("/simulation/run?days=2&seed=99&start_date=2026-02-01")
        assert response.status_code == 200
        assert response.json() == {
            "days": 2,
            "seed": 99,
            "start_date": "2026-02-01",
            "end_date": "2026-02-02",
        }
    finally:
        app.dependency_overrides.clear()

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.simulator.engine import DigitalTwinSimulator


def _client(db):
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    return client


def _seeded_client(db, days=5):
    DigitalTwinSimulator(db, seed=42).run(days=days)
    return _client(db)


def test_health():
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}


def test_dimensions_include_suppliers(db):
    DigitalTwinSimulator(db, seed=42).seed_master_data()
    client = _client(db)
    try:
        response = client.get("/dimensions")
        assert response.status_code == 200
        payload = response.json()
        assert len(payload["warehouses"]) == 3
        assert len(payload["suppliers"]) == 5
        assert len(payload["skus"]) == 30
    finally:
        app.dependency_overrides.clear()


def test_simulation_endpoint_accepts_seed_and_start_date(db):
    client = _client(db)
    try:
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


def test_inventory_endpoint_returns_snapshots(db):
    client = _seeded_client(db)
    try:
        response = client.get("/inventory?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert "on_hand" in data[0]
        assert "warehouse_id" in data[0]
    finally:
        app.dependency_overrides.clear()


def test_inventory_date_range_filter(db):
    client = _seeded_client(db, days=10)
    try:
        response = client.get("/inventory?date_from=2026-01-03&date_to=2026-01-05&limit=5000")
        assert response.status_code == 200
        dates = {row["snapshot_date"] for row in response.json()}
        assert all(d >= "2026-01-03" and d <= "2026-01-05" for d in dates)
    finally:
        app.dependency_overrides.clear()


def test_events_endpoint_returns_events(db):
    client = _seeded_client(db)
    try:
        response = client.get("/events?limit=50")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert "event_type" in data[0]
    finally:
        app.dependency_overrides.clear()


def test_events_event_type_filter(db):
    client = _seeded_client(db)
    try:
        response = client.get("/events?event_type=STOCKOUT&limit=500")
        assert response.status_code == 200
        for row in response.json():
            assert row["event_type"] == "STOCKOUT"
    finally:
        app.dependency_overrides.clear()


def test_events_invalid_event_type_returns_422(db):
    client = _seeded_client(db)
    try:
        response = client.get("/events?event_type=NOT_A_REAL_TYPE")
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_events_date_range_filter(db):
    client = _seeded_client(db, days=10)
    try:
        response = client.get("/events?date_from=2026-01-03&date_to=2026-01-04&limit=5000")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        for row in data:
            day = row["event_time"][:10]
            assert day >= "2026-01-03" and day <= "2026-01-04"
    finally:
        app.dependency_overrides.clear()


def test_kpi_summary_returns_latest(db):
    client = _seeded_client(db)
    try:
        response = client.get("/kpis/summary")
        assert response.status_code == 200
        data = response.json()
        assert "fill_rate" in data
        assert "total_cost" in data
    finally:
        app.dependency_overrides.clear()


def test_kpi_summary_404_when_no_data(db):
    client = _client(db)
    try:
        response = client.get("/kpis/summary")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_kpi_network_returns_rows(db):
    client = _seeded_client(db, days=5)
    try:
        response = client.get("/kpis/network")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 5
        assert "kpi_date" in data[0]
    finally:
        app.dependency_overrides.clear()


def test_kpi_network_date_range(db):
    client = _seeded_client(db, days=10)
    try:
        response = client.get("/kpis/network?date_from=2026-01-03&date_to=2026-01-07")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 5
        assert all("2026-01-03" <= row["kpi_date"] <= "2026-01-07" for row in data)
    finally:
        app.dependency_overrides.clear()


def test_kpi_warehouse_returns_rows(db):
    client = _seeded_client(db)
    try:
        response = client.get("/kpis/warehouse")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert "warehouse_id" in data[0]
    finally:
        app.dependency_overrides.clear()


def test_kpi_warehouse_filter_by_id(db):
    client = _seeded_client(db)
    try:
        response = client.get("/kpis/warehouse?warehouse_id=1")
        assert response.status_code == 200
        for row in response.json():
            assert row["warehouse_id"] == 1
    finally:
        app.dependency_overrides.clear()


def test_kpi_sku_returns_all_skus(db):
    client = _seeded_client(db)
    try:
        response = client.get("/kpis/sku")
        assert response.status_code == 200
        data = response.json()
        # Number of SKUs matches seeded master data (30 SKUs)
        dims = client.get("/dimensions").json()
        assert len(data) == len(dims["skus"])
        row = data[0]
        assert "sku_code" in row
        assert "fill_rate" in row
        assert "total_stockout_units" in row
    finally:
        app.dependency_overrides.clear()


def test_kpi_supplier_returns_all_suppliers(db):
    client = _seeded_client(db)
    try:
        response = client.get("/kpis/supplier")
        assert response.status_code == 200
        data = response.json()
        # Number of suppliers matches seeded master data (5 suppliers)
        dims = client.get("/dimensions").json()
        assert len(data) == len(dims["suppliers"])
        row = data[0]
        assert "supplier_code" in row
        assert "delay_rate" in row
        assert "total_purchase_orders" in row
    finally:
        app.dependency_overrides.clear()


def test_simulation_days_1_edge_case(db):
    client = _client(db)
    try:
        response = client.post("/simulation/run?days=1&seed=1")
        assert response.status_code == 200
        assert response.json()["days"] == 1
        assert response.json()["start_date"] == response.json()["end_date"]
    finally:
        app.dependency_overrides.clear()


def test_simulation_reset_false_appends_data(db):
    client = _client(db)
    try:
        client.post("/simulation/run?days=3&seed=42&start_date=2026-01-01")
        response = client.post("/simulation/run?days=3&seed=42&start_date=2026-01-04&reset=false")
        assert response.status_code == 200
        # network KPIs should now cover 6 days
        kpi_response = client.get("/kpis/network")
        assert len(kpi_response.json()) == 6
    finally:
        app.dependency_overrides.clear()


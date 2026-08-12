import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import InventorySnapshot, Scenario, SimulationRun, SupplyChainEvent
from app.db.session import get_db
from app.main import app
from app.services.scenarios import _pct_change
from app.simulator.engine import DigitalTwinSimulator


def api_client(db):
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_run_ids_are_unique_and_multiple_results_are_preserved(db):
    first = DigitalTwinSimulator(db, seed=11).run(days=2)
    second = DigitalTwinSimulator(db, seed=11).run(days=2)

    assert first["run_id"] != second["run_id"]
    assert db.scalar(select(func.count()).select_from(SimulationRun)) == 2
    assert db.scalar(select(func.count()).select_from(InventorySnapshot)) == 2 * 2 * 3 * 30
    assert {row.run_id for row in db.scalars(select(InventorySnapshot))} == {
        first["run_id"],
        second["run_id"],
    }


@pytest.mark.parametrize(
    ("scenario_type", "expected_event", "parameters"),
    [
        ("demand_spike", "DEMAND_SPIKE", {"warehouse_id": 1, "demand_multiplier": 2.0}),
        ("supplier_shutdown", "SUPPLIER_SHUTDOWN", {"supplier_id": 1}),
        (
            "supplier_capacity_reduction",
            "CAPACITY_REDUCTION",
            {"supplier_id": 1, "capacity_reduction_pct": 0.5},
        ),
        ("lead_time_increase", "LEAD_TIME_INCREASE", {"supplier_id": 1, "lead_time_multiplier": 2.0}),
        ("transportation_delay", "TRANSPORTATION_DELAY", {"supplier_id": 1, "delay_days": 3}),
        ("warehouse_shutdown", "WAREHOUSE_SHUTDOWN", {"warehouse_id": 1}),
        ("inventory_loss", "INVENTORY_LOSS", {"warehouse_id": 1, "inventory_loss_pct": 0.25}),
    ],
)
def test_every_disruption_is_applied_to_its_target(db, scenario_type, expected_event, parameters):
    simulator = DigitalTwinSimulator(db, seed=42)
    simulator.seed_master_data()
    scenario = Scenario(
        name=f"test-{scenario_type}",
        scenario_type=scenario_type,
        start_day=1,
        end_day=30,
        **parameters,
    )
    db.add(scenario)
    db.commit()

    result = simulator.run(days=30, scenario=scenario)
    events = list(
        db.scalars(
            select(SupplyChainEvent).where(
                SupplyChainEvent.run_id == result["run_id"],
                SupplyChainEvent.event_type == expected_event,
            )
        )
    )
    assert events
    if scenario.warehouse_id:
        assert all(event.warehouse_id == scenario.warehouse_id for event in events)
    if scenario.supplier_id:
        assert all(event.supplier_id == scenario.supplier_id for event in events)


def test_scenario_api_executes_pair_and_exposes_history_results_and_comparison(db):
    client = api_client(db)
    try:
        created = client.post(
            "/scenarios",
            json={
                "name": "Warehouse 1 demand surge",
                "scenario_type": "demand_spike",
                "start_day": 1,
                "end_day": 5,
                "warehouse_id": 1,
                "demand_multiplier": 2.0,
            },
        )
        assert created.status_code == 201
        scenario_id = created.json()["id"]

        executed = client.post(
            f"/scenarios/{scenario_id}/runs",
            json={"days": 5, "seed": 73, "start_date": "2026-03-01"},
        )
        assert executed.status_code == 201
        payload = executed.json()
        baseline_id = payload["baseline_run"]["run_id"]
        scenario_run_id = payload["scenario_run"]["run_id"]
        assert baseline_id != scenario_run_id
        assert payload["scenario_run"]["baseline_run_id"] == baseline_id
        assert payload["scenario_run"]["scenario_id"] == scenario_id

        history = client.get("/runs?limit=1&offset=0")
        assert history.status_code == 200
        assert len(history.json()["items"]) == 1

        result = client.get(f"/runs/{scenario_run_id}/results")
        assert result.status_code == 200
        assert result.json()["counts"]["inventory_snapshots"] == 5 * 3 * 30

        comparison = client.get(f"/runs/{scenario_run_id}/comparison")
        assert comparison.status_code == 200
        comparison_payload = comparison.json()
        assert comparison_payload["baseline_run_id"] == baseline_id
        assert comparison_payload["scenario_run_id"] == scenario_run_id
        assert comparison_payload["delta"]["demand_units"] > 0
        assert comparison_payload["percent_change"]["demand_units"] > 0

        baseline_result = client.get(f"/runs/{baseline_id}/results")
        assert baseline_result.status_code == 200
        assert baseline_result.json()["counts"]["inventory_snapshots"] == 5 * 3 * 30
    finally:
        app.dependency_overrides.clear()


def test_scenario_validation_and_missing_resources(db):
    client = api_client(db)
    try:
        invalid_range = client.post(
            "/scenarios",
            json={
                "name": "invalid range",
                "scenario_type": "demand_spike",
                "start_day": 5,
                "end_day": 2,
                "demand_multiplier": 2.0,
            },
        )
        assert invalid_range.status_code == 422

        missing_supplier = client.post(
            "/scenarios",
            json={
                "name": "missing supplier",
                "scenario_type": "supplier_shutdown",
                "start_day": 1,
                "end_day": 2,
                "supplier_id": 999,
            },
        )
        assert missing_supplier.status_code == 422
        assert client.get("/scenarios/not-a-real-id").status_code == 404
        assert client.get("/runs/not-a-real-id").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_scenario_ids_are_unique_and_duplicate_names_conflict(db):
    client = api_client(db)
    try:
        payload = {
            "scenario_type": "inventory_loss",
            "start_day": 1,
            "end_day": 1,
            "warehouse_id": 1,
            "inventory_loss_pct": 0.1,
        }
        first = client.post("/scenarios", json={"name": "loss-a", **payload})
        second = client.post("/scenarios", json={"name": "loss-b", **payload})
        assert first.status_code == second.status_code == 201
        assert first.json()["id"] != second.json()["id"]
        assert client.post("/scenarios", json={"name": "loss-a", **payload}).status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_percentage_change_handles_zero_baseline():
    assert _pct_change(5, 0) is None


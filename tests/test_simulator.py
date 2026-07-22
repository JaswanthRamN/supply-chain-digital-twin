from sqlalchemy import func, select
from app.db.models import DailyNetworkKPI, InventorySnapshot, SKU, SupplyChainEvent, Warehouse
from app.simulator.engine import DigitalTwinSimulator

def test_simulation_builds_expected_dimensions_and_facts(db):
    result = DigitalTwinSimulator(db, seed=42).run(days=5)
    assert result["days"] == 5
    assert db.scalar(select(func.count()).select_from(Warehouse)) == 3
    assert db.scalar(select(func.count()).select_from(SKU)) == 30
    assert db.scalar(select(func.count()).select_from(InventorySnapshot)) == 3*30*5
    assert db.scalar(select(func.count()).select_from(SupplyChainEvent)) > 0
    assert db.scalar(select(func.count()).select_from(DailyNetworkKPI)) == 5

def test_simulation_is_deterministic(db):
    sim = DigitalTwinSimulator(db, seed=7); sim.run(days=3)
    first = [(x.kpi_date, x.demand_units, round(x.fill_rate,6)) for x in db.scalars(select(DailyNetworkKPI).order_by(DailyNetworkKPI.kpi_date))]
    sim = DigitalTwinSimulator(db, seed=7); sim.run(days=3)
    second = [(x.kpi_date, x.demand_units, round(x.fill_rate,6)) for x in db.scalars(select(DailyNetworkKPI).order_by(DailyNetworkKPI.kpi_date))]
    assert first == second

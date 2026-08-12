from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas import ScenarioCreate, ScenarioRunRequest
from app.db.models import (
    DailyNetworkKPI,
    Scenario,
    ScenarioComparison,
    SimulationRun,
    SKU,
    Supplier,
    Warehouse,
)
from app.simulator.engine import DigitalTwinSimulator


class ScenarioNotFoundError(LookupError):
    pass


class InvalidTargetError(ValueError):
    pass


def validate_targets(db: Session, payload: ScenarioCreate) -> None:
    checks = (
        (Warehouse, payload.warehouse_id, "warehouse"),
        (Supplier, payload.supplier_id, "supplier"),
        (SKU, payload.sku_id, "SKU"),
    )
    for model, target_id, label in checks:
        if target_id is not None and db.get(model, target_id) is None:
            raise InvalidTargetError(f"{label} {target_id} does not exist")
    if payload.sku_id is not None and payload.supplier_id is not None:
        sku = db.get(SKU, payload.sku_id)
        if sku and sku.supplier_id != payload.supplier_id:
            raise InvalidTargetError("SKU does not belong to the selected supplier")


def create_scenario(db: Session, payload: ScenarioCreate) -> Scenario:
    DigitalTwinSimulator(db).seed_master_data()
    validate_targets(db, payload)
    scenario = Scenario(**payload.model_dump(mode="json"))
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    return scenario


def get_scenario(db: Session, scenario_id: str) -> Scenario:
    scenario = db.get(Scenario, scenario_id)
    if scenario is None:
        raise ScenarioNotFoundError(f"scenario {scenario_id} was not found")
    return scenario


def _aggregate_run(db: Session, run_id: str) -> dict:
    demand, fulfilled, stockouts, avg_inventory, total_cost = db.execute(
        select(
            func.coalesce(func.sum(DailyNetworkKPI.demand_units), 0),
            func.coalesce(func.sum(DailyNetworkKPI.fulfilled_units), 0),
            func.coalesce(func.sum(DailyNetworkKPI.stockout_units), 0),
            func.coalesce(func.avg(DailyNetworkKPI.inventory_units), 0),
            func.coalesce(func.sum(DailyNetworkKPI.total_cost), 0),
        ).where(DailyNetworkKPI.run_id == run_id)
    ).one()
    demand = int(demand or 0)
    fulfilled = int(fulfilled or 0)
    return {
        "demand_units": demand,
        "fulfilled_units": fulfilled,
        "stockout_units": int(stockouts or 0),
        "fill_rate": fulfilled / demand if demand else 1.0,
        "average_inventory_units": int(round(float(avg_inventory or 0))),
        "total_cost": Decimal(str(total_cost or 0)),
    }


def _pct_change(delta: int | float | Decimal, baseline: int | float | Decimal) -> float | None:
    if baseline == 0:
        return None
    return float(delta / baseline * 100)


def _recovery_days(db: Session, baseline_run_id: str, scenario_run_id: str, scenario: Scenario) -> int | None:
    baseline = {
        row.kpi_date: row.fill_rate
        for row in db.scalars(
            select(DailyNetworkKPI)
            .where(DailyNetworkKPI.run_id == baseline_run_id)
            .order_by(DailyNetworkKPI.kpi_date)
        )
    }
    scenario_rows = list(
        db.scalars(
            select(DailyNetworkKPI)
            .where(DailyNetworkKPI.run_id == scenario_run_id)
            .order_by(DailyNetworkKPI.kpi_date)
        )
    )
    for day_number, row in enumerate(scenario_rows, 1):
        if day_number > scenario.end_day and row.fill_rate >= baseline.get(row.kpi_date, 1.0):
            return day_number - scenario.end_day
    return None


def create_comparison(
    db: Session,
    *,
    baseline_run_id: str,
    scenario_run_id: str,
    scenario: Scenario,
) -> ScenarioComparison:
    baseline = _aggregate_run(db, baseline_run_id)
    changed = _aggregate_run(db, scenario_run_id)
    fill_delta = changed["fill_rate"] - baseline["fill_rate"]
    demand_delta = changed["demand_units"] - baseline["demand_units"]
    fulfilled_delta = changed["fulfilled_units"] - baseline["fulfilled_units"]
    stockout_delta = changed["stockout_units"] - baseline["stockout_units"]
    inventory_delta = changed["average_inventory_units"] - baseline["average_inventory_units"]
    cost_delta = changed["total_cost"] - baseline["total_cost"]
    comparison = ScenarioComparison(
        baseline_run_id=baseline_run_id,
        scenario_run_id=scenario_run_id,
        fill_rate_delta=fill_delta,
        fill_rate_pct_change=_pct_change(fill_delta, baseline["fill_rate"]),
        demand_delta=demand_delta,
        demand_pct_change=_pct_change(demand_delta, baseline["demand_units"]),
        fulfilled_delta=fulfilled_delta,
        fulfilled_pct_change=_pct_change(fulfilled_delta, baseline["fulfilled_units"]),
        stockout_delta=stockout_delta,
        stockout_pct_change=_pct_change(stockout_delta, baseline["stockout_units"]),
        inventory_delta=inventory_delta,
        inventory_pct_change=_pct_change(inventory_delta, baseline["average_inventory_units"]),
        total_cost_delta=cost_delta,
        total_cost_pct_change=_pct_change(cost_delta, baseline["total_cost"]),
        recovery_days=_recovery_days(db, baseline_run_id, scenario_run_id, scenario),
    )
    db.add(comparison)
    db.commit()
    db.refresh(comparison)
    return comparison


def execute_scenario_pair(db: Session, scenario: Scenario, request: ScenarioRunRequest) -> dict:
    if scenario.end_day > request.days:
        raise ValueError("scenario date range must fall within the simulation window")
    baseline = DigitalTwinSimulator(db, request.seed).run(
        days=request.days,
        start_date=request.start_date,
    )
    changed = DigitalTwinSimulator(db, request.seed).run(
        days=request.days,
        start_date=request.start_date,
        scenario=scenario,
        baseline_run_id=baseline["run_id"],
    )
    comparison = create_comparison(
        db,
        baseline_run_id=baseline["run_id"],
        scenario_run_id=changed["run_id"],
        scenario=scenario,
    )
    return {
        "baseline_run": baseline,
        "scenario_run": changed,
        "comparison_id": comparison.id,
    }


def comparison_payload(db: Session, comparison: ScenarioComparison) -> dict:
    return {
        "id": comparison.id,
        "baseline_run_id": comparison.baseline_run_id,
        "scenario_run_id": comparison.scenario_run_id,
        "baseline": _aggregate_run(db, comparison.baseline_run_id),
        "scenario": _aggregate_run(db, comparison.scenario_run_id),
        "delta": {
            "fill_rate": comparison.fill_rate_delta,
            "demand_units": comparison.demand_delta,
            "fulfilled_units": comparison.fulfilled_delta,
            "stockout_units": comparison.stockout_delta,
            "average_inventory_units": comparison.inventory_delta,
            "total_cost": comparison.total_cost_delta,
        },
        "percent_change": {
            "fill_rate": comparison.fill_rate_pct_change,
            "demand_units": comparison.demand_pct_change,
            "fulfilled_units": comparison.fulfilled_pct_change,
            "stockout_units": comparison.stockout_pct_change,
            "average_inventory_units": comparison.inventory_pct_change,
            "total_cost": comparison.total_cost_pct_change,
        },
        "recovery_days": comparison.recovery_days,
        "created_at": comparison.created_at,
    }


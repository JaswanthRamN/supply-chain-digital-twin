from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DailyNetworkKPI,
    ScenarioRun,
)
from app.simulator.disruptions import DisruptionConfig
from app.simulator.engine import DigitalTwinSimulator


def _kpi_snapshot(db: Session) -> list[dict]:
    rows = db.scalars(select(DailyNetworkKPI).order_by(DailyNetworkKPI.kpi_date)).all()
    return [
        {
            "kpi_date": str(row.kpi_date),
            "demand_units": row.demand_units,
            "fulfilled_units": row.fulfilled_units,
            "stockout_units": row.stockout_units,
            "fill_rate": row.fill_rate,
            "inventory_units": row.inventory_units,
            "total_cost": float(row.total_cost),
        }
        for row in rows
    ]


def _aggregate(kpis: list[dict]) -> dict:
    if not kpis:
        return {"fill_rate": 0.0, "total_cost": 0.0, "stockout_units": 0}
    total_demand = sum(k["demand_units"] for k in kpis)
    total_fulfilled = sum(k["fulfilled_units"] for k in kpis)
    fill_rate = total_fulfilled / total_demand if total_demand else 1.0
    return {
        "fill_rate": fill_rate,
        "total_cost": sum(k["total_cost"] for k in kpis),
        "stockout_units": sum(k["stockout_units"] for k in kpis),
    }


def run_scenario(
    db: Session,
    *,
    name: str,
    days: int,
    seed: int,
    start_date: date,
    disruptions: DisruptionConfig,
    compare_to_baseline: bool = True,
) -> ScenarioRun:
    """Run a disruption scenario, optionally compare against a clean baseline."""

    # --- Run baseline (no disruptions) ---
    baseline_kpis: list[dict] | None = None
    if compare_to_baseline:
        DigitalTwinSimulator(db, seed=seed).run(days=days, start_date=start_date, reset=True)
        baseline_kpis = _kpi_snapshot(db)
        baseline_agg = _aggregate(baseline_kpis)

    # --- Run disrupted scenario ---
    DigitalTwinSimulator(db, seed=seed, disruptions=disruptions).run(
        days=days, start_date=start_date, reset=True
    )
    scenario_kpis = _kpi_snapshot(db)
    scenario_agg = _aggregate(scenario_kpis)

    delta_fill_rate = None
    delta_total_cost = None
    delta_stockout_units = None
    if baseline_kpis is not None:
        delta_fill_rate = scenario_agg["fill_rate"] - baseline_agg["fill_rate"]
        delta_total_cost = Decimal(str(scenario_agg["total_cost"] - baseline_agg["total_cost"]))
        delta_stockout_units = scenario_agg["stockout_units"] - baseline_agg["stockout_units"]

    scenario_run = ScenarioRun(
        name=name,
        days=days,
        seed=seed,
        start_date=start_date,
        end_date=date.fromisoformat(scenario_kpis[-1]["kpi_date"]) if scenario_kpis else start_date,
        disruption_config=json.dumps(
            {
                "supplier_shutdowns": [
                    {
                        "supplier_id": s.supplier_id,
                        "start_date": str(s.start_date),
                        "end_date": str(s.end_date),
                    }
                    for s in disruptions.supplier_shutdowns
                ],
                "demand_spikes": [
                    {
                        "multiplier": d.multiplier,
                        "start_date": str(d.start_date),
                        "end_date": str(d.end_date),
                        "sku_ids": d.sku_ids,
                        "warehouse_ids": d.warehouse_ids,
                    }
                    for d in disruptions.demand_spikes
                ],
                "transfer_delays": [
                    {
                        "extra_days": t.extra_days,
                        "start_date": str(t.start_date),
                        "end_date": str(t.end_date),
                    }
                    for t in disruptions.transfer_delays
                ],
            }
        ),
        delta_fill_rate=delta_fill_rate,
        delta_total_cost=delta_total_cost,
        delta_stockout_units=delta_stockout_units,
        kpi_snapshot=json.dumps(scenario_kpis),
    )
    db.add(scenario_run)
    db.commit()
    db.refresh(scenario_run)
    return scenario_run


def list_scenario_runs(db: Session) -> list[ScenarioRun]:
    return list(db.scalars(select(ScenarioRun).order_by(ScenarioRun.created_at.desc())).all())


def get_scenario_run(db: Session, run_id: int) -> ScenarioRun | None:
    return db.get(ScenarioRun, run_id)

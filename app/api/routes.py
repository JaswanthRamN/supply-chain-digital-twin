from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.schemas import (
    DimensionsOut,
    InventorySnapshotOut,
    LowStockAlertOut,
    NetworkKPIOut,
    ScenarioRequest,
    ScenarioRunOut,
    SimulationResult,
    SKUKPIOut,
    SupplierKPIOut,
    SupplyChainEventOut,
    WarehouseKPIOut,
)
from app.core.config import settings
from app.db.session import get_db
from app.services import query as svc
from app.services import scenario as scn_svc
from app.simulator.disruptions import (
    DemandSpike,
    DisruptionConfig,
    SupplierShutdown,
    TransferDelay,
)
from app.simulator.engine import DigitalTwinSimulator
from app.simulator.events import EventType

router = APIRouter()


# ── Utility ──────────────────────────────────────────────────────────────────

@router.get("/health", tags=["Utility"])
def health():
    return {"status": "ok"}


# ── Simulation ───────────────────────────────────────────────────────────────

@router.post("/simulation/run", response_model=SimulationResult, tags=["Simulation"])
def run_simulation(
    days: int = Query(30, ge=1, le=365),
    seed: int = Query(settings.simulation_seed),
    start_date: date = Query(date(2026, 1, 1)),
    reset: bool = Query(True),
    db: Session = Depends(get_db),
):
    result = DigitalTwinSimulator(db, seed).run(days=days, start_date=start_date, reset=reset)
    return result


@router.post("/simulation/scenario", response_model=ScenarioRunOut, tags=["Simulation"])
def run_scenario(
    body: ScenarioRequest = Body(...),
    db: Session = Depends(get_db),
):
    disruptions = DisruptionConfig(
        supplier_shutdowns=[
            SupplierShutdown(
                supplier_id=s.supplier_id,
                start_date=s.start_date,
                end_date=s.end_date,
            )
            for s in body.supplier_shutdowns
        ],
        demand_spikes=[
            DemandSpike(
                multiplier=d.multiplier,
                start_date=d.start_date,
                end_date=d.end_date,
                sku_ids=d.sku_ids,
                warehouse_ids=d.warehouse_ids,
            )
            for d in body.demand_spikes
        ],
        transfer_delays=[
            TransferDelay(
                extra_days=t.extra_days,
                start_date=t.start_date,
                end_date=t.end_date,
            )
            for t in body.transfer_delays
        ],
    )
    return scn_svc.run_scenario(
        db,
        name=body.name,
        days=body.days,
        seed=body.seed,
        start_date=body.start_date,
        disruptions=disruptions,
        compare_to_baseline=body.compare_to_baseline,
    )


@router.get("/simulation/scenarios", response_model=list[ScenarioRunOut], tags=["Simulation"])
def list_scenarios(db: Session = Depends(get_db)):
    return scn_svc.list_scenario_runs(db)


@router.get("/simulation/scenarios/{run_id}", response_model=ScenarioRunOut, tags=["Simulation"])
def get_scenario(run_id: int, db: Session = Depends(get_db)):
    run = scn_svc.get_scenario_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Scenario run {run_id} not found.")
    return run


# ── Inventory ────────────────────────────────────────────────────────────────

@router.get("/inventory", response_model=list[InventorySnapshotOut], tags=["Inventory"])
def inventory(
    snapshot_date: date | None = None,
    warehouse_id: int | None = None,
    sku_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return svc.get_inventory(
        db,
        snapshot_date=snapshot_date,
        warehouse_id=warehouse_id,
        sku_id=sku_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


@router.get("/inventory/low-stock", response_model=list[LowStockAlertOut], tags=["Inventory"])
def low_stock(
    warehouse_id: int | None = None,
    db: Session = Depends(get_db),
):
    return svc.get_low_stock_alerts(db, warehouse_id=warehouse_id)


# ── Events ────────────────────────────────────────────────────────────────────

@router.get("/events", response_model=list[SupplyChainEventOut], tags=["Events"])
def events(
    event_type: str | None = None,
    warehouse_id: int | None = None,
    sku_id: int | None = None,
    supplier_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(200, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    if event_type is not None:
        valid = {e.value for e in EventType}
        if event_type not in valid:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid event_type '{event_type}'. Valid values: {sorted(valid)}",
            )
    return svc.get_events(
        db,
        event_type=event_type,
        warehouse_id=warehouse_id,
        sku_id=sku_id,
        supplier_id=supplier_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


# ── KPIs ──────────────────────────────────────────────────────────────────────

@router.get("/kpis/summary", response_model=NetworkKPIOut, tags=["KPIs"])
def summary(db: Session = Depends(get_db)):
    latest = svc.get_kpi_summary(db)
    if latest is None:
        raise HTTPException(status_code=404, detail="No simulation data. Run a simulation first.")
    return latest


@router.get("/kpis/network", response_model=list[NetworkKPIOut], tags=["KPIs"])
def network(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    return svc.get_network_kpis(db, date_from=date_from, date_to=date_to)


@router.get("/kpis/warehouse", response_model=list[WarehouseKPIOut], tags=["KPIs"])
def warehouse_kpis(
    warehouse_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    return svc.get_warehouse_kpis(db, warehouse_id=warehouse_id, date_from=date_from, date_to=date_to)


@router.get("/kpis/sku", response_model=list[SKUKPIOut], tags=["KPIs"])
def sku_kpis(db: Session = Depends(get_db)):
    return svc.get_sku_kpis(db)


@router.get("/kpis/supplier", response_model=list[SupplierKPIOut], tags=["KPIs"])
def supplier_kpis(db: Session = Depends(get_db)):
    return svc.get_supplier_kpis(db)


# ── Dimensions ────────────────────────────────────────────────────────────────

@router.get("/dimensions", response_model=DimensionsOut, tags=["Dimensions"])
def dimensions(db: Session = Depends(get_db)):
    raw = svc.get_dimensions(db)
    return DimensionsOut(
        warehouses=raw["warehouses"],
        suppliers=raw["suppliers"],
        skus=raw["skus"],
    )

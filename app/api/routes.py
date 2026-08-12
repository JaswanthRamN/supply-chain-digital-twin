from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas import ScenarioCreate, ScenarioRunRequest
from app.core.config import settings
from app.db.models import (
    DailyNetworkKPI,
    DailyWarehouseKPI,
    InventorySnapshot,
    Scenario,
    ScenarioComparison,
    SimulationRun,
    SKU,
    Supplier,
    SupplyChainEvent,
    Warehouse,
)
from app.db.session import get_db
from app.services.scenarios import (
    InvalidTargetError,
    ScenarioNotFoundError,
    comparison_payload,
    create_scenario,
    execute_scenario_pair,
    get_scenario,
)
from app.simulator.engine import DigitalTwinSimulator

router = APIRouter()


def rows(items):
    return [{column.name: getattr(item, column.name) for column in item.__table__.columns} for item in items]


def require_run(db: Session, run_id: str) -> SimulationRun:
    run = db.get(SimulationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} was not found")
    return run


def latest_run_id(db: Session) -> str | None:
    return db.scalar(
        select(SimulationRun.id)
        .where(SimulationRun.status == "COMPLETED")
        .order_by(SimulationRun.created_at.desc())
        .limit(1)
    )


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/simulation/run")
def run_simulation(
    days: int = Query(30, ge=1, le=365),
    seed: int = Query(settings.simulation_seed),
    start_date: date = Query(date(2026, 1, 1)),
    reset: bool = Query(False, description="Deprecated; run history is always preserved"),
    db: Session = Depends(get_db),
):
    return DigitalTwinSimulator(db, seed).run(days=days, start_date=start_date, reset=reset)


@router.post("/scenarios", status_code=status.HTTP_201_CREATED)
def add_scenario(payload: ScenarioCreate, db: Session = Depends(get_db)):
    try:
        return rows([create_scenario(db, payload)])[0]
    except InvalidTargetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="scenario name already exists") from exc


@router.get("/scenarios")
def scenarios(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    items = db.scalars(
        select(Scenario).order_by(Scenario.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return {"items": rows(items), "offset": offset, "limit": limit}


@router.get("/scenarios/{scenario_id}")
def scenario_detail(scenario_id: str, db: Session = Depends(get_db)):
    try:
        return rows([get_scenario(db, scenario_id)])[0]
    except ScenarioNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/scenarios/{scenario_id}/runs", status_code=status.HTTP_201_CREATED)
def run_scenario(
    scenario_id: str,
    payload: ScenarioRunRequest,
    db: Session = Depends(get_db),
):
    try:
        scenario = get_scenario(db, scenario_id)
        return execute_scenario_pair(db, scenario, payload)
    except ScenarioNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs")
def runs(
    scenario_id: str | None = None,
    run_type: str | None = Query(default=None, pattern="^(baseline|scenario)$"),
    run_status: str | None = Query(default=None, alias="status"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    stmt = select(SimulationRun).order_by(SimulationRun.created_at.desc()).offset(offset).limit(limit)
    if scenario_id:
        stmt = stmt.where(SimulationRun.scenario_id == scenario_id)
    if run_type:
        stmt = stmt.where(SimulationRun.run_type == run_type)
    if run_status:
        stmt = stmt.where(SimulationRun.status == run_status.upper())
    items = db.scalars(stmt).all()
    return {"items": rows(items), "offset": offset, "limit": limit}


@router.get("/runs/{run_id}")
def run_detail(run_id: str, db: Session = Depends(get_db)):
    return rows([require_run(db, run_id)])[0]


@router.get("/runs/{run_id}/results")
def run_results(run_id: str, db: Session = Depends(get_db)):
    require_run(db, run_id)
    network = db.scalars(
        select(DailyNetworkKPI)
        .where(DailyNetworkKPI.run_id == run_id)
        .order_by(DailyNetworkKPI.kpi_date)
    ).all()
    return {
        "run_id": run_id,
        "network_kpis": rows(network),
        "counts": {
            "inventory_snapshots": db.scalar(
                select(func.count()).select_from(InventorySnapshot).where(InventorySnapshot.run_id == run_id)
            ),
            "events": db.scalar(
                select(func.count()).select_from(SupplyChainEvent).where(SupplyChainEvent.run_id == run_id)
            ),
        },
    }


@router.get("/runs/{scenario_run_id}/comparison")
def run_comparison(scenario_run_id: str, db: Session = Depends(get_db)):
    require_run(db, scenario_run_id)
    comparison = db.scalar(
        select(ScenarioComparison).where(ScenarioComparison.scenario_run_id == scenario_run_id)
    )
    if comparison is None:
        raise HTTPException(status_code=404, detail="comparison was not found")
    return comparison_payload(db, comparison)


@router.get("/inventory")
def inventory(
    run_id: str | None = None,
    snapshot_date: date | None = None,
    warehouse_id: int | None = None,
    sku_id: int | None = None,
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    selected_run = run_id or latest_run_id(db)
    stmt = select(InventorySnapshot).order_by(InventorySnapshot.snapshot_date.desc()).limit(limit)
    if selected_run:
        stmt = stmt.where(InventorySnapshot.run_id == selected_run)
    if snapshot_date:
        stmt = stmt.where(InventorySnapshot.snapshot_date == snapshot_date)
    if warehouse_id:
        stmt = stmt.where(InventorySnapshot.warehouse_id == warehouse_id)
    if sku_id:
        stmt = stmt.where(InventorySnapshot.sku_id == sku_id)
    return rows(db.scalars(stmt).all())


@router.get("/events")
def events(
    run_id: str | None = None,
    event_type: str | None = None,
    warehouse_id: int | None = None,
    sku_id: int | None = None,
    supplier_id: int | None = None,
    limit: int = Query(200, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    selected_run = run_id or latest_run_id(db)
    stmt = select(SupplyChainEvent).order_by(SupplyChainEvent.event_time.desc(), SupplyChainEvent.id.desc()).limit(limit)
    if selected_run:
        stmt = stmt.where(SupplyChainEvent.run_id == selected_run)
    if event_type:
        stmt = stmt.where(SupplyChainEvent.event_type == event_type)
    if warehouse_id:
        stmt = stmt.where(SupplyChainEvent.warehouse_id == warehouse_id)
    if sku_id:
        stmt = stmt.where(SupplyChainEvent.sku_id == sku_id)
    if supplier_id:
        stmt = stmt.where(SupplyChainEvent.supplier_id == supplier_id)
    return rows(db.scalars(stmt).all())


@router.get("/kpis/summary")
def summary(run_id: str | None = None, db: Session = Depends(get_db)):
    selected_run = run_id or latest_run_id(db)
    if not selected_run:
        return {}
    latest = db.scalar(
        select(DailyNetworkKPI)
        .where(DailyNetworkKPI.run_id == selected_run)
        .order_by(DailyNetworkKPI.kpi_date.desc())
        .limit(1)
    )
    return rows([latest])[0] if latest else {}


@router.get("/kpis/network")
def network(run_id: str | None = None, db: Session = Depends(get_db)):
    selected_run = run_id or latest_run_id(db)
    stmt = select(DailyNetworkKPI).order_by(DailyNetworkKPI.kpi_date)
    if selected_run:
        stmt = stmt.where(DailyNetworkKPI.run_id == selected_run)
    return rows(db.scalars(stmt).all())


@router.get("/kpis/warehouse")
def warehouse_kpis(
    run_id: str | None = None,
    warehouse_id: int | None = None,
    db: Session = Depends(get_db),
):
    selected_run = run_id or latest_run_id(db)
    stmt = select(DailyWarehouseKPI).order_by(DailyWarehouseKPI.kpi_date, DailyWarehouseKPI.warehouse_id)
    if selected_run:
        stmt = stmt.where(DailyWarehouseKPI.run_id == selected_run)
    if warehouse_id:
        stmt = stmt.where(DailyWarehouseKPI.warehouse_id == warehouse_id)
    return rows(db.scalars(stmt).all())


@router.get("/dimensions")
def dimensions(db: Session = Depends(get_db)):
    return {
        "warehouses": rows(db.scalars(select(Warehouse).order_by(Warehouse.id)).all()),
        "suppliers": rows(db.scalars(select(Supplier).order_by(Supplier.id)).all()),
        "skus": rows(db.scalars(select(SKU).order_by(SKU.id)).all()),
    }

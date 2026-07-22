from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    DailyNetworkKPI,
    DailyWarehouseKPI,
    InventorySnapshot,
    SKU,
    Supplier,
    SupplyChainEvent,
    Warehouse,
)
from app.db.session import get_db
from app.simulator.engine import DigitalTwinSimulator

router = APIRouter()


def rows(items):
    return [{column.name: getattr(item, column.name) for column in item.__table__.columns} for item in items]


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/simulation/run")
def run_simulation(
    days: int = Query(30, ge=1, le=365),
    seed: int = Query(settings.simulation_seed),
    start_date: date = Query(date(2026, 1, 1)),
    reset: bool = Query(True),
    db: Session = Depends(get_db),
):
    return DigitalTwinSimulator(db, seed).run(days=days, start_date=start_date, reset=reset)


@router.get("/inventory")
def inventory(
    snapshot_date: date | None = None,
    warehouse_id: int | None = None,
    sku_id: int | None = None,
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    stmt = select(InventorySnapshot).order_by(InventorySnapshot.snapshot_date.desc()).limit(limit)
    if snapshot_date:
        stmt = stmt.where(InventorySnapshot.snapshot_date == snapshot_date)
    if warehouse_id:
        stmt = stmt.where(InventorySnapshot.warehouse_id == warehouse_id)
    if sku_id:
        stmt = stmt.where(InventorySnapshot.sku_id == sku_id)
    return rows(db.scalars(stmt).all())


@router.get("/events")
def events(
    event_type: str | None = None,
    warehouse_id: int | None = None,
    sku_id: int | None = None,
    supplier_id: int | None = None,
    limit: int = Query(200, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    stmt = select(SupplyChainEvent).order_by(SupplyChainEvent.event_time.desc(), SupplyChainEvent.id.desc()).limit(limit)
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
def summary(db: Session = Depends(get_db)):
    latest = db.scalar(select(DailyNetworkKPI).order_by(DailyNetworkKPI.kpi_date.desc()).limit(1))
    return rows([latest])[0] if latest else {}


@router.get("/kpis/network")
def network(db: Session = Depends(get_db)):
    return rows(db.scalars(select(DailyNetworkKPI).order_by(DailyNetworkKPI.kpi_date)).all())


@router.get("/kpis/warehouse")
def warehouse_kpis(
    warehouse_id: int | None = None,
    db: Session = Depends(get_db),
):
    stmt = select(DailyWarehouseKPI).order_by(DailyWarehouseKPI.kpi_date, DailyWarehouseKPI.warehouse_id)
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

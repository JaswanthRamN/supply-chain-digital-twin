from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import DailyNetworkKPI, DailyWarehouseKPI, InventorySnapshot, SKU, SupplyChainEvent, Warehouse
from app.simulator.engine import DigitalTwinSimulator
from app.core.config import settings

router = APIRouter()

def rows(items):
    return [{c.name: getattr(x,c.name) for c in x.__table__.columns} for x in items]

@router.get("/health")
def health(): return {"status":"ok"}

@router.post("/simulation/run")
def run_simulation(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    return DigitalTwinSimulator(db, settings.simulation_seed).run(days=days)

@router.get("/inventory")
def inventory(snapshot_date: date | None = None, limit: int = Query(500, le=5000), db: Session = Depends(get_db)):
    stmt = select(InventorySnapshot).order_by(InventorySnapshot.snapshot_date.desc()).limit(limit)
    if snapshot_date: stmt = stmt.where(InventorySnapshot.snapshot_date == snapshot_date)
    return rows(db.scalars(stmt).all())

@router.get("/events")
def events(event_type: str | None = None, limit: int = Query(200, le=5000), db: Session = Depends(get_db)):
    stmt = select(SupplyChainEvent).order_by(SupplyChainEvent.event_time.desc()).limit(limit)
    if event_type: stmt = stmt.where(SupplyChainEvent.event_type == event_type)
    return rows(db.scalars(stmt).all())

@router.get("/kpis/summary")
def summary(db: Session = Depends(get_db)):
    latest = db.scalar(select(DailyNetworkKPI).order_by(DailyNetworkKPI.kpi_date.desc()).limit(1))
    return rows([latest])[0] if latest else {}

@router.get("/kpis/network")
def network(db: Session = Depends(get_db)):
    return rows(db.scalars(select(DailyNetworkKPI).order_by(DailyNetworkKPI.kpi_date)).all())

@router.get("/kpis/warehouse")
def warehouse_kpis(db: Session = Depends(get_db)):
    return rows(db.scalars(select(DailyWarehouseKPI).order_by(DailyWarehouseKPI.kpi_date, DailyWarehouseKPI.warehouse_id)).all())

@router.get("/dimensions")
def dimensions(db: Session = Depends(get_db)):
    return {"warehouses": rows(db.scalars(select(Warehouse)).all()), "skus": rows(db.scalars(select(SKU)).all())}

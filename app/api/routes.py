from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.schemas import (
    DimensionsOut,
    InventorySnapshotOut,
    NetworkKPIOut,
    SimulationResult,
    SKUKPIOut,
    SupplierKPIOut,
    SupplyChainEventOut,
    WarehouseKPIOut,
)
from app.core.config import settings
from app.db.session import get_db
from app.services import query as svc
from app.simulator.engine import DigitalTwinSimulator
from app.simulator.events import EventType

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/simulation/run", response_model=SimulationResult)
def run_simulation(
    days: int = Query(30, ge=1, le=365),
    seed: int = Query(settings.simulation_seed),
    start_date: date = Query(date(2026, 1, 1)),
    reset: bool = Query(True),
    db: Session = Depends(get_db),
):
    result = DigitalTwinSimulator(db, seed).run(days=days, start_date=start_date, reset=reset)
    return result


@router.get("/inventory", response_model=list[InventorySnapshotOut])
def inventory(
    snapshot_date: date | None = None,
    warehouse_id: int | None = None,
    sku_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(500, ge=1, le=5000),
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
    )


@router.get("/events", response_model=list[SupplyChainEventOut])
def events(
    event_type: str | None = None,
    warehouse_id: int | None = None,
    sku_id: int | None = None,
    supplier_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(200, ge=1, le=5000),
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
    )


@router.get("/kpis/summary", response_model=NetworkKPIOut)
def summary(db: Session = Depends(get_db)):
    latest = svc.get_kpi_summary(db)
    if latest is None:
        raise HTTPException(status_code=404, detail="No simulation data. Run a simulation first.")
    return latest


@router.get("/kpis/network", response_model=list[NetworkKPIOut])
def network(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    return svc.get_network_kpis(db, date_from=date_from, date_to=date_to)


@router.get("/kpis/warehouse", response_model=list[WarehouseKPIOut])
def warehouse_kpis(
    warehouse_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    return svc.get_warehouse_kpis(db, warehouse_id=warehouse_id, date_from=date_from, date_to=date_to)


@router.get("/kpis/sku", response_model=list[SKUKPIOut])
def sku_kpis(db: Session = Depends(get_db)):
    return svc.get_sku_kpis(db)


@router.get("/kpis/supplier", response_model=list[SupplierKPIOut])
def supplier_kpis(db: Session = Depends(get_db)):
    return svc.get_supplier_kpis(db)


@router.get("/dimensions", response_model=DimensionsOut)
def dimensions(db: Session = Depends(get_db)):
    raw = svc.get_dimensions(db)
    return DimensionsOut(
        warehouses=raw["warehouses"],
        suppliers=raw["suppliers"],
        skus=raw["skus"],
    )


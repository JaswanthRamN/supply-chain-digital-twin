from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    DailyNetworkKPI,
    DailyWarehouseKPI,
    InventorySnapshot,
    SKU,
    Supplier,
    SupplyChainEvent,
    Warehouse,
)
from app.simulator.events import (
    DEMAND_CREATED,
    PURCHASE_ORDER_CREATED,
    STOCKOUT,
    SUPPLIER_DELAY,
    EventType,
)


def get_inventory(
    db: Session,
    *,
    snapshot_date: date | None = None,
    warehouse_id: int | None = None,
    sku_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[InventorySnapshot]:
    stmt = (
        select(InventorySnapshot)
        .order_by(InventorySnapshot.snapshot_date.desc())
        .limit(limit)
        .offset(offset)
    )
    if snapshot_date:
        stmt = stmt.where(InventorySnapshot.snapshot_date == snapshot_date)
    if warehouse_id:
        stmt = stmt.where(InventorySnapshot.warehouse_id == warehouse_id)
    if sku_id:
        stmt = stmt.where(InventorySnapshot.sku_id == sku_id)
    if date_from:
        stmt = stmt.where(InventorySnapshot.snapshot_date >= date_from)
    if date_to:
        stmt = stmt.where(InventorySnapshot.snapshot_date <= date_to)
    return list(db.scalars(stmt).all())


def get_events(
    db: Session,
    *,
    event_type: str | None = None,
    warehouse_id: int | None = None,
    sku_id: int | None = None,
    supplier_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[SupplyChainEvent]:
    stmt = (
        select(SupplyChainEvent)
        .order_by(SupplyChainEvent.event_time.desc(), SupplyChainEvent.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if event_type:
        stmt = stmt.where(SupplyChainEvent.event_type == event_type)
    if warehouse_id:
        stmt = stmt.where(SupplyChainEvent.warehouse_id == warehouse_id)
    if sku_id:
        stmt = stmt.where(SupplyChainEvent.sku_id == sku_id)
    if supplier_id:
        stmt = stmt.where(SupplyChainEvent.supplier_id == supplier_id)
    if date_from:
        stmt = stmt.where(func.date(SupplyChainEvent.event_time) >= date_from.isoformat())
    if date_to:
        stmt = stmt.where(func.date(SupplyChainEvent.event_time) <= date_to.isoformat())
    return list(db.scalars(stmt).all())


def get_network_kpis(
    db: Session,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[DailyNetworkKPI]:
    stmt = select(DailyNetworkKPI).order_by(DailyNetworkKPI.kpi_date)
    if date_from:
        stmt = stmt.where(DailyNetworkKPI.kpi_date >= date_from)
    if date_to:
        stmt = stmt.where(DailyNetworkKPI.kpi_date <= date_to)
    return list(db.scalars(stmt).all())


def get_warehouse_kpis(
    db: Session,
    *,
    warehouse_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[DailyWarehouseKPI]:
    stmt = select(DailyWarehouseKPI).order_by(
        DailyWarehouseKPI.kpi_date, DailyWarehouseKPI.warehouse_id
    )
    if warehouse_id:
        stmt = stmt.where(DailyWarehouseKPI.warehouse_id == warehouse_id)
    if date_from:
        stmt = stmt.where(DailyWarehouseKPI.kpi_date >= date_from)
    if date_to:
        stmt = stmt.where(DailyWarehouseKPI.kpi_date <= date_to)
    return list(db.scalars(stmt).all())


def get_sku_kpis(db: Session) -> list[dict]:
    # Single aggregated query: demand and stockout rolled up per SKU
    agg = (
        select(
            SupplyChainEvent.sku_id,
            func.coalesce(
                func.sum(
                    case(
                        (SupplyChainEvent.event_type == DEMAND_CREATED, SupplyChainEvent.quantity),
                        else_=0,
                    )
                ),
                0,
            ).label("total_demand"),
            func.coalesce(
                func.sum(
                    case(
                        (SupplyChainEvent.event_type == STOCKOUT, SupplyChainEvent.quantity),
                        else_=0,
                    )
                ),
                0,
            ).label("total_stockout"),
            func.coalesce(
                func.sum(
                    case(
                        (SupplyChainEvent.event_type == STOCKOUT, SupplyChainEvent.cost),
                        else_=0,
                    )
                ),
                0,
            ).label("total_shortage_cost"),
        )
        .where(SupplyChainEvent.event_type.in_([DEMAND_CREATED, STOCKOUT]))
        .group_by(SupplyChainEvent.sku_id)
    )
    agg_by_sku: dict[int, tuple] = {
        row.sku_id: row for row in db.execute(agg).all()
    }

    skus = list(db.scalars(select(SKU).order_by(SKU.id)).all())
    results = []
    for sku in skus:
        row = agg_by_sku.get(sku.id)
        total_demand = int(row.total_demand) if row else 0
        total_stockout = int(row.total_stockout) if row else 0
        total_shortage_cost = Decimal(str(row.total_shortage_cost)) if row else Decimal("0")
        fulfilled = total_demand - total_stockout
        fill_rate = fulfilled / total_demand if total_demand else 1.0
        results.append(
            {
                "sku_id": sku.id,
                "sku_code": sku.code,
                "description": sku.description,
                "total_stockout_units": total_stockout,
                "total_shortage_cost": total_shortage_cost,
                "total_demand_units": total_demand,
                "fill_rate": fill_rate,
            }
        )
    return results


def get_supplier_kpis(db: Session) -> list[dict]:
    # Aggregate PO counts per supplier in one query
    po_counts = {
        row.supplier_id: int(row.total_pos)
        for row in db.execute(
            select(
                SupplyChainEvent.supplier_id,
                func.count(SupplyChainEvent.id).label("total_pos"),
            )
            .where(SupplyChainEvent.event_type == PURCHASE_ORDER_CREATED)
            .group_by(SupplyChainEvent.supplier_id)
        ).all()
    }

    # Fetch all delay events in one query
    delay_events = list(
        db.scalars(
            select(SupplyChainEvent).where(SupplyChainEvent.event_type == SUPPLIER_DELAY)
        ).all()
    )
    delay_counts: dict[int, int] = {}
    delay_days_sums: dict[int, float] = {}
    for e in delay_events:
        sid = e.supplier_id
        if sid is None:
            continue
        delay_counts[sid] = delay_counts.get(sid, 0) + 1
        days_val = json.loads(e.details).get("delay_days", 0) if e.details else 0
        delay_days_sums[sid] = delay_days_sums.get(sid, 0.0) + float(days_val)

    suppliers = list(db.scalars(select(Supplier).order_by(Supplier.id)).all())
    results = []
    for supplier in suppliers:
        total_pos = po_counts.get(supplier.id, 0)
        total_delays = delay_counts.get(supplier.id, 0)
        delay_days_sum = delay_days_sums.get(supplier.id, 0.0)
        delay_rate = total_delays / total_pos if total_pos else 0.0
        avg_delay_days = delay_days_sum / total_delays if total_delays else 0.0
        results.append(
            {
                "supplier_id": supplier.id,
                "supplier_code": supplier.code,
                "name": supplier.name,
                "total_purchase_orders": total_pos,
                "total_delays": total_delays,
                "delay_rate": delay_rate,
                "avg_delay_days": avg_delay_days,
            }
        )
    return results


def get_dimensions(db: Session) -> dict:
    return {
        "warehouses": list(db.scalars(select(Warehouse).order_by(Warehouse.id)).all()),
        "suppliers": list(db.scalars(select(Supplier).order_by(Supplier.id)).all()),
        "skus": list(db.scalars(select(SKU).order_by(SKU.id)).all()),
    }


def get_kpi_summary(db: Session) -> DailyNetworkKPI | None:
    return db.scalar(
        select(DailyNetworkKPI).order_by(DailyNetworkKPI.kpi_date.desc()).limit(1)
    )


def get_low_stock_alerts(db: Session, *, warehouse_id: int | None = None) -> list[dict]:
    """Return inventory rows where on_hand <= reorder_point on the latest snapshot date."""
    latest_date_subq = select(func.max(InventorySnapshot.snapshot_date)).scalar_subquery()
    stmt = (
        select(InventorySnapshot, SKU)
        .join(SKU, SKU.id == InventorySnapshot.sku_id)
        .where(
            InventorySnapshot.snapshot_date == latest_date_subq,
            InventorySnapshot.on_hand <= SKU.reorder_point,
        )
        .order_by(InventorySnapshot.warehouse_id, SKU.code)
    )
    if warehouse_id:
        stmt = stmt.where(InventorySnapshot.warehouse_id == warehouse_id)
    rows = db.execute(stmt).all()
    return [
        {
            "warehouse_id": snap.warehouse_id,
            "sku_id": snap.sku_id,
            "sku_code": sku.code,
            "on_hand": snap.on_hand,
            "reorder_point": sku.reorder_point,
            "shortfall": sku.reorder_point - snap.on_hand,
        }
        for snap, sku in rows
    ]

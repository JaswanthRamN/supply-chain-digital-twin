from datetime import date
from decimal import Decimal
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from app.db.models import DailyNetworkKPI, DailyWarehouseKPI, InventorySnapshot, SKU, SupplyChainEvent, Warehouse

DEMAND = "DEMAND"
FULFILLMENT = "FULFILLMENT"
STOCKOUT = "STOCKOUT"

def refresh_analytics(db: Session) -> None:
    dates = db.scalars(select(func.date(SupplyChainEvent.event_time)).distinct()).all()
    db.execute(delete(DailyWarehouseKPI))
    db.execute(delete(DailyNetworkKPI))
    warehouses = db.scalars(select(Warehouse)).all()
    for raw_day in dates:
        day = date.fromisoformat(str(raw_day))
        network = dict(demand=0, fulfilled=0, stockout=0, inventory=0, value=Decimal("0"), cost=Decimal("0"))
        for wh in warehouses:
            def qty(event_type: str) -> int:
                return int(db.scalar(select(func.coalesce(func.sum(SupplyChainEvent.quantity), 0)).where(
                    func.date(SupplyChainEvent.event_time) == day.isoformat(),
                    SupplyChainEvent.warehouse_id == wh.id,
                    SupplyChainEvent.event_type == event_type,
                )) or 0)
            demand, fulfilled, stockout = qty(DEMAND), qty(FULFILLMENT), qty(STOCKOUT)
            costs = {}
            for event_type, key in [("HOLDING_COST","holding"),("PURCHASE_ORDER","ordering"),("TRANSFER","transfer"),("STOCKOUT","shortage")]:
                costs[key] = Decimal(str(db.scalar(select(func.coalesce(func.sum(SupplyChainEvent.cost), 0)).where(
                    func.date(SupplyChainEvent.event_time) == day.isoformat(),
                    SupplyChainEvent.warehouse_id == wh.id,
                    SupplyChainEvent.event_type == event_type,
                )) or 0))
            inv_units = int(db.scalar(select(func.coalesce(func.sum(InventorySnapshot.on_hand), 0)).where(
                InventorySnapshot.snapshot_date == day, InventorySnapshot.warehouse_id == wh.id)) or 0)
            inv_value = Decimal(str(db.scalar(select(func.coalesce(func.sum(InventorySnapshot.on_hand * SKU.unit_cost), 0)).join(SKU, SKU.id == InventorySnapshot.sku_id).where(
                InventorySnapshot.snapshot_date == day, InventorySnapshot.warehouse_id == wh.id)) or 0))
            total_cost = sum(costs.values(), Decimal("0"))
            db.add(DailyWarehouseKPI(kpi_date=day, warehouse_id=wh.id, demand_units=demand,
                fulfilled_units=fulfilled, stockout_units=stockout,
                fill_rate=(fulfilled / demand if demand else 1.0), inventory_units=inv_units,
                inventory_value=inv_value, holding_cost=costs["holding"], ordering_cost=costs["ordering"],
                transfer_cost=costs["transfer"], shortage_cost=costs["shortage"], total_cost=total_cost))
            network["demand"] += demand; network["fulfilled"] += fulfilled; network["stockout"] += stockout
            network["inventory"] += inv_units; network["value"] += inv_value; network["cost"] += total_cost
        db.add(DailyNetworkKPI(kpi_date=day, demand_units=network["demand"], fulfilled_units=network["fulfilled"],
            stockout_units=network["stockout"], fill_rate=(network["fulfilled"] / network["demand"] if network["demand"] else 1.0),
            inventory_units=network["inventory"], inventory_value=network["value"], total_cost=network["cost"]))
    db.commit()

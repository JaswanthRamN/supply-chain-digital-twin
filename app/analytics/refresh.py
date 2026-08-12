from datetime import date
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import DailyNetworkKPI, DailyWarehouseKPI, InventorySnapshot, SKU, SupplyChainEvent, Warehouse
from app.simulator.events import (
    DEMAND_CREATED,
    DEMAND_FULFILLED,
    HOLDING_COST,
    INVENTORY_TRANSFER,
    PURCHASE_ORDER_CREATED,
    STOCKOUT,
)


def _decimal(value) -> Decimal:
    return Decimal(str(value or 0))


def refresh_analytics(db: Session, run_id: str) -> None:
    dates = db.scalars(
        select(func.date(SupplyChainEvent.event_time))
        .where(SupplyChainEvent.run_id == run_id)
        .distinct()
        .order_by(func.date(SupplyChainEvent.event_time))
    ).all()
    db.execute(delete(DailyWarehouseKPI).where(DailyWarehouseKPI.run_id == run_id))
    db.execute(delete(DailyNetworkKPI).where(DailyNetworkKPI.run_id == run_id))
    warehouses = list(db.scalars(select(Warehouse).order_by(Warehouse.id)).all())

    for raw_day in dates:
        day = date.fromisoformat(str(raw_day))
        network = {
            "demand": 0,
            "fulfilled": 0,
            "stockout": 0,
            "inventory": 0,
            "value": Decimal("0"),
            "holding": Decimal("0"),
            "ordering": Decimal("0"),
            "transfer": Decimal("0"),
            "shortage": Decimal("0"),
        }

        for warehouse in warehouses:
            def event_quantity(event_type: str) -> int:
                return int(
                    db.scalar(
                        select(func.coalesce(func.sum(SupplyChainEvent.quantity), 0)).where(
                            func.date(SupplyChainEvent.event_time) == day.isoformat(),
                            SupplyChainEvent.run_id == run_id,
                            SupplyChainEvent.warehouse_id == warehouse.id,
                            SupplyChainEvent.event_type == event_type,
                        )
                    )
                    or 0
                )

            def event_cost(event_type: str) -> Decimal:
                return _decimal(
                    db.scalar(
                        select(func.coalesce(func.sum(SupplyChainEvent.cost), 0)).where(
                            func.date(SupplyChainEvent.event_time) == day.isoformat(),
                            SupplyChainEvent.run_id == run_id,
                            SupplyChainEvent.warehouse_id == warehouse.id,
                            SupplyChainEvent.event_type == event_type,
                        )
                    )
                )

            demand = event_quantity(DEMAND_CREATED)
            fulfilled = event_quantity(DEMAND_FULFILLED)
            stockout = event_quantity(STOCKOUT)
            holding_cost = event_cost(HOLDING_COST)
            ordering_cost = event_cost(PURCHASE_ORDER_CREATED)
            transfer_cost = event_cost(INVENTORY_TRANSFER)
            shortage_cost = event_cost(STOCKOUT)

            inventory_units = int(
                db.scalar(
                    select(func.coalesce(func.sum(InventorySnapshot.on_hand), 0)).where(
                        InventorySnapshot.snapshot_date == day,
                        InventorySnapshot.run_id == run_id,
                        InventorySnapshot.warehouse_id == warehouse.id,
                    )
                )
                or 0
            )
            inventory_value = _decimal(
                db.scalar(
                    select(func.coalesce(func.sum(InventorySnapshot.on_hand * SKU.unit_cost), 0))
                    .join(SKU, SKU.id == InventorySnapshot.sku_id)
                    .where(
                        InventorySnapshot.snapshot_date == day,
                        InventorySnapshot.run_id == run_id,
                        InventorySnapshot.warehouse_id == warehouse.id,
                    )
                )
            )
            total_cost = holding_cost + ordering_cost + transfer_cost + shortage_cost

            db.add(
                DailyWarehouseKPI(
                    run_id=run_id,
                    kpi_date=day,
                    warehouse_id=warehouse.id,
                    demand_units=demand,
                    fulfilled_units=fulfilled,
                    stockout_units=stockout,
                    fill_rate=(fulfilled / demand if demand else 1.0),
                    inventory_units=inventory_units,
                    inventory_value=inventory_value,
                    holding_cost=holding_cost,
                    ordering_cost=ordering_cost,
                    transfer_cost=transfer_cost,
                    shortage_cost=shortage_cost,
                    total_cost=total_cost,
                )
            )

            network["demand"] += demand
            network["fulfilled"] += fulfilled
            network["stockout"] += stockout
            network["inventory"] += inventory_units
            network["value"] += inventory_value
            network["holding"] += holding_cost
            network["ordering"] += ordering_cost
            network["transfer"] += transfer_cost
            network["shortage"] += shortage_cost

        total_cost = network["holding"] + network["ordering"] + network["transfer"] + network["shortage"]
        db.add(
            DailyNetworkKPI(
                run_id=run_id,
                kpi_date=day,
                demand_units=network["demand"],
                fulfilled_units=network["fulfilled"],
                stockout_units=network["stockout"],
                fill_rate=(network["fulfilled"] / network["demand"] if network["demand"] else 1.0),
                inventory_units=network["inventory"],
                inventory_value=network["value"],
                holding_cost=network["holding"],
                ordering_cost=network["ordering"],
                transfer_cost=network["transfer"],
                shortage_cost=network["shortage"],
                total_cost=total_cost,
            )
        )
    db.commit()

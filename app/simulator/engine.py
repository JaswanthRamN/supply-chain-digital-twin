from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analytics.refresh import refresh_analytics
from app.db.models import SKU, InventorySnapshot, Supplier, SupplyChainEvent, Warehouse
from app.simulator.disruptions import DisruptionConfig
from app.simulator.events import (
    BACKORDER_CREATED,
    BACKORDER_FULFILLED,
    DEMAND_CREATED,
    DEMAND_FULFILLED,
    HOLDING_COST,
    INVENTORY_TRANSFER,
    PURCHASE_ORDER_CREATED,
    SHIPMENT_RECEIVED,
    STOCKOUT,
    SUPPLIER_DELAY,
)


@dataclass(frozen=True)
class ScheduledReceipt:
    warehouse_id: int
    sku_id: int
    supplier_id: int
    quantity: int
    purchase_order_reference: str


class DigitalTwinSimulator:
    """Deterministic synthetic supply-chain simulation.

    Supports Milestone 8 disruption scenarios via an optional DisruptionConfig.
    """

    def __init__(self, db: Session, seed: int = 42, disruptions: DisruptionConfig | None = None):
        self.db = db
        self.seed = seed
        self.rng = random.Random(seed)
        self.disruptions = disruptions or DisruptionConfig()

    def seed_master_data(self) -> None:
        if self.db.scalar(select(Warehouse.id).limit(1)):
            return

        warehouses = [
            Warehouse(code=f"WH{i}", name=name, region=region)
            for i, (name, region) in enumerate(
                [
                    ("East Distribution Center", "East"),
                    ("Central Distribution Center", "Central"),
                    ("West Distribution Center", "West"),
                ],
                1,
            )
        ]
        suppliers = [
            Supplier(
                code=f"SUP{i:02d}",
                name=f"Supplier {i}",
                base_lead_time_days=2 + i,
                reliability=min(0.99, 0.82 + i * 0.03),
            )
            for i in range(1, 6)
        ]
        self.db.add_all(warehouses + suppliers)
        self.db.flush()

        for i in range(1, 31):
            supplier = suppliers[(i - 1) % 5]
            self.db.add(
                SKU(
                    code=f"SKU-{i:03d}",
                    description=f"Component {i}",
                    supplier_id=supplier.id,
                    unit_cost=Decimal(str(8 + i * 1.35)),
                    holding_cost_daily=Decimal("0.04"),
                    shortage_cost=Decimal("7.50"),
                    reorder_point=35 + (i % 6) * 5,
                    reorder_qty=80 + (i % 5) * 10,
                )
            )
        self.db.commit()

    def reset_operational_data(self) -> None:
        self.db.execute(delete(InventorySnapshot))
        self.db.execute(delete(SupplyChainEvent))
        self.db.commit()

    def _add_event(
        self,
        *,
        event_time: datetime,
        event_type: str,
        warehouse_id: int | None = None,
        sku_id: int | None = None,
        supplier_id: int | None = None,
        quantity: int = 0,
        cost: Decimal = Decimal(0),
        reference: str | None = None,
        details: dict | None = None,
    ) -> None:
        self.db.add(
            SupplyChainEvent(
                event_time=event_time,
                event_type=event_type,
                warehouse_id=warehouse_id,
                sku_id=sku_id,
                supplier_id=supplier_id,
                quantity=quantity,
                cost=cost,
                reference=reference,
                details=json.dumps(details, sort_keys=True) if details else None,
            )
        )

    def run(self, days: int = 30, start_date: date | None = None, reset: bool = True) -> dict:
        if days < 1:
            raise ValueError("days must be at least 1")

        self.rng = random.Random(self.seed)
        self.seed_master_data()
        if reset:
            self.reset_operational_data()

        start = start_date or date(2026, 1, 1)
        warehouses = list(self.db.scalars(select(Warehouse).order_by(Warehouse.id)).all())
        skus = list(self.db.scalars(select(SKU).order_by(SKU.id)).all())
        suppliers = {s.id: s for s in self.db.scalars(select(Supplier)).all()}

        inventory = {(w.id, s.id): self.rng.randint(70, 150) for w in warehouses for s in skus}
        backorders = defaultdict(int)
        on_order = defaultdict(int)
        arrivals: dict[date, list[ScheduledReceipt]] = defaultdict(list)
        po_sequence = 0

        for offset in range(days):
            day = start + timedelta(days=offset)
            ts = datetime.combine(day, time(9))

            for receipt in arrivals.pop(day, []):
                key = (receipt.warehouse_id, receipt.sku_id)
                on_order[key] -= receipt.quantity
                inventory[key] += receipt.quantity
                self._add_event(
                    event_time=ts,
                    event_type=SHIPMENT_RECEIVED,
                    warehouse_id=receipt.warehouse_id,
                    sku_id=receipt.sku_id,
                    supplier_id=receipt.supplier_id,
                    quantity=receipt.quantity,
                    reference=receipt.purchase_order_reference,
                )

                backorder_fulfilled = min(backorders[key], inventory[key])
                if backorder_fulfilled:
                    inventory[key] -= backorder_fulfilled
                    backorders[key] -= backorder_fulfilled
                    self._add_event(
                        event_time=ts,
                        event_type=BACKORDER_FULFILLED,
                        warehouse_id=receipt.warehouse_id,
                        sku_id=receipt.sku_id,
                        supplier_id=receipt.supplier_id,
                        quantity=backorder_fulfilled,
                        reference=receipt.purchase_order_reference,
                    )

            # Transfer delay extra days active today
            transfer_extra = self.disruptions.transfer_extra_days(day)

            for warehouse in warehouses:
                for sku in skus:
                    key = (warehouse.id, sku.id)

                    # Apply demand spike multiplier
                    base_demand = max(0, int(self.rng.gauss(7 + sku.id % 5, 3)))
                    multiplier = self.disruptions.demand_multiplier(day, sku.id, warehouse.id)
                    demand = max(0, int(base_demand * multiplier))

                    available = inventory[key]
                    fulfilled = min(available, demand)
                    shortage = demand - fulfilled
                    inventory[key] -= fulfilled

                    self._add_event(
                        event_time=ts,
                        event_type=DEMAND_CREATED,
                        warehouse_id=warehouse.id,
                        sku_id=sku.id,
                        quantity=demand,
                    )
                    self._add_event(
                        event_time=ts,
                        event_type=DEMAND_FULFILLED,
                        warehouse_id=warehouse.id,
                        sku_id=sku.id,
                        quantity=fulfilled,
                    )

                    if shortage:
                        donor = max(
                            (candidate for candidate in warehouses if candidate.id != warehouse.id),
                            key=lambda candidate: inventory[(candidate.id, sku.id)],
                        )
                        donor_key = (donor.id, sku.id)
                        transferable = max(0, inventory[donor_key] - sku.reorder_point)
                        transfer_qty = min(shortage, transferable)
                        if transfer_qty:
                            if transfer_extra > 0:
                                # Delayed transfer: schedule arrival instead of same-day
                                arrival_date = day + timedelta(days=transfer_extra)
                                arrivals[arrival_date].append(
                                    ScheduledReceipt(
                                        warehouse_id=warehouse.id,
                                        sku_id=sku.id,
                                        supplier_id=suppliers[sku.supplier_id].id,
                                        quantity=transfer_qty,
                                        purchase_order_reference=f"TRANSFER-DELAYED-{day.isoformat()}",
                                    )
                                )
                                inventory[donor_key] -= transfer_qty
                                on_order[key] += transfer_qty
                            else:
                                inventory[donor_key] -= transfer_qty
                                fulfilled += transfer_qty
                                shortage -= transfer_qty
                            self._add_event(
                                event_time=ts,
                                event_type=INVENTORY_TRANSFER,
                                warehouse_id=warehouse.id,
                                sku_id=sku.id,
                                quantity=transfer_qty,
                                cost=Decimal("2.00") * transfer_qty,
                                reference=f"FROM-{donor.code}",
                                details={
                                    "source_warehouse_id": donor.id,
                                    "destination_warehouse_id": warehouse.id,
                                    "delayed_days": transfer_extra,
                                },
                            )
                            if transfer_extra == 0:
                                self._add_event(
                                    event_time=ts,
                                    event_type=DEMAND_FULFILLED,
                                    warehouse_id=warehouse.id,
                                    sku_id=sku.id,
                                    quantity=transfer_qty,
                                    reference="EMERGENCY_TRANSFER",
                                )

                    if shortage:
                        backorders[key] += shortage
                        shortage_cost = sku.shortage_cost * shortage
                        self._add_event(
                            event_time=ts,
                            event_type=STOCKOUT,
                            warehouse_id=warehouse.id,
                            sku_id=sku.id,
                            quantity=shortage,
                            cost=shortage_cost,
                        )
                        self._add_event(
                            event_time=ts,
                            event_type=BACKORDER_CREATED,
                            warehouse_id=warehouse.id,
                            sku_id=sku.id,
                            quantity=shortage,
                        )

                    inventory_position = inventory[key] + on_order[key] - backorders[key]
                    if inventory_position <= sku.reorder_point:
                        supplier = suppliers[sku.supplier_id]
                        # Skip PO if supplier is shut down
                        if self.disruptions.is_supplier_shutdown(day, supplier.id):
                            self._add_event(
                                event_time=ts,
                                event_type=SUPPLIER_DELAY,
                                warehouse_id=warehouse.id,
                                sku_id=sku.id,
                                supplier_id=supplier.id,
                                quantity=sku.reorder_qty,
                                details={
                                    "delay_days": 0,
                                    "indefinite": True,
                                    "reason": "supplier_shutdown",
                                },
                            )
                        else:
                            po_sequence += 1
                            po_reference = f"PO-{day:%Y%m%d}-{po_sequence:05d}"
                            delay_days = 0 if self.rng.random() <= supplier.reliability else self.rng.randint(1, 4)
                            arrival_date = day + timedelta(days=supplier.base_lead_time_days + delay_days)
                            arrivals[arrival_date].append(
                                ScheduledReceipt(
                                    warehouse_id=warehouse.id,
                                    sku_id=sku.id,
                                    supplier_id=supplier.id,
                                    quantity=sku.reorder_qty,
                                    purchase_order_reference=po_reference,
                                )
                            )
                            on_order[key] += sku.reorder_qty
                            self._add_event(
                                event_time=ts,
                                event_type=PURCHASE_ORDER_CREATED,
                                warehouse_id=warehouse.id,
                                sku_id=sku.id,
                                supplier_id=supplier.id,
                                quantity=sku.reorder_qty,
                                cost=Decimal("35.00"),
                                reference=po_reference,
                                details={
                                    "expected_arrival_date": arrival_date.isoformat(),
                                    "delay_days": delay_days,
                                },
                            )
                            if delay_days:
                                self._add_event(
                                    event_time=ts,
                                    event_type=SUPPLIER_DELAY,
                                    warehouse_id=warehouse.id,
                                    sku_id=sku.id,
                                    supplier_id=supplier.id,
                                    quantity=sku.reorder_qty,
                                    reference=po_reference,
                                    details={
                                        "delay_days": delay_days,
                                        "revised_arrival_date": arrival_date.isoformat(),
                                    },
                                )

                    holding_cost = sku.holding_cost_daily * inventory[key]
                    self._add_event(
                        event_time=ts,
                        event_type=HOLDING_COST,
                        warehouse_id=warehouse.id,
                        sku_id=sku.id,
                        quantity=inventory[key],
                        cost=holding_cost,
                    )
                    self.db.add(
                        InventorySnapshot(
                            snapshot_date=day,
                            warehouse_id=warehouse.id,
                            sku_id=sku.id,
                            on_hand=inventory[key],
                            on_order=on_order[key],
                            backorder=backorders[key],
                        )
                    )
            self.db.commit()

        refresh_analytics(self.db)
        return {
            "days": days,
            "seed": self.seed,
            "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=days - 1)).isoformat(),
        }

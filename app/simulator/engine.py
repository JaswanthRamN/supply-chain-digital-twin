from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import json
import math
import random
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analytics.refresh import refresh_analytics
from app.db.models import (
    DailyNetworkKPI,
    DailyWarehouseKPI,
    InventorySnapshot,
    Scenario,
    SimulationRun,
    SKU,
    Supplier,
    SupplyChainEvent,
    Warehouse,
    utc_now,
)
from app.simulator.events import (
    BACKORDER_CREATED,
    BACKORDER_FULFILLED,
    CAPACITY_REDUCTION,
    DEMAND_CREATED,
    DEMAND_FULFILLED,
    DEMAND_SPIKE,
    HOLDING_COST,
    INVENTORY_LOSS,
    INVENTORY_TRANSFER,
    LEAD_TIME_INCREASE,
    PURCHASE_ORDER_CREATED,
    SHIPMENT_RECEIVED,
    STOCKOUT,
    SUPPLIER_DELAY,
    SUPPLIER_SHUTDOWN,
    TRANSPORTATION_DELAY,
    WAREHOUSE_SHUTDOWN,
)


@dataclass(frozen=True)
class ScheduledReceipt:
    warehouse_id: int
    sku_id: int
    supplier_id: int
    quantity: int
    purchase_order_reference: str


class DigitalTwinSimulator:
    """Deterministic, run-scoped supply-chain simulation."""

    def __init__(self, db: Session, seed: int = 42):
        self.db = db
        self.seed = seed
        self.rng = random.Random(seed)
        self.run_id: str | None = None

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

    def reset_operational_data(self, run_id: str) -> None:
        """Remove only one run's facts; historical runs are never globally deleted."""
        self.db.execute(delete(DailyWarehouseKPI).where(DailyWarehouseKPI.run_id == run_id))
        self.db.execute(delete(DailyNetworkKPI).where(DailyNetworkKPI.run_id == run_id))
        self.db.execute(delete(InventorySnapshot).where(InventorySnapshot.run_id == run_id))
        self.db.execute(delete(SupplyChainEvent).where(SupplyChainEvent.run_id == run_id))
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
        cost: Decimal = Decimal("0"),
        reference: str | None = None,
        details: dict | None = None,
    ) -> None:
        if self.run_id is None:
            raise RuntimeError("simulation run has not been created")
        self.db.add(
            SupplyChainEvent(
                run_id=self.run_id,
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

    @staticmethod
    def _active(scenario: Scenario | None, day_number: int) -> bool:
        return bool(scenario and scenario.start_day <= day_number <= scenario.end_day)

    @staticmethod
    def _matches(
        scenario: Scenario,
        *,
        warehouse_id: int | None = None,
        supplier_id: int | None = None,
        sku_id: int | None = None,
    ) -> bool:
        return (
            (scenario.warehouse_id is None or scenario.warehouse_id == warehouse_id)
            and (scenario.supplier_id is None or scenario.supplier_id == supplier_id)
            and (scenario.sku_id is None or scenario.sku_id == sku_id)
        )

    def run(
        self,
        days: int = 30,
        start_date: date | None = None,
        reset: bool = False,
        *,
        scenario: Scenario | None = None,
        baseline_run_id: str | None = None,
    ) -> dict:
        if days < 1:
            raise ValueError("days must be at least 1")
        if scenario and scenario.end_day > days:
            raise ValueError("scenario date range must fall within the simulation window")

        self.rng = random.Random(self.seed)
        self.seed_master_data()
        start = start_date or date(2026, 1, 1)
        end = start + timedelta(days=days - 1)
        run = SimulationRun(
            id=str(uuid4()),
            run_type="scenario" if scenario else "baseline",
            scenario_id=scenario.id if scenario else None,
            baseline_run_id=baseline_run_id,
            seed=self.seed,
            simulation_start=start,
            simulation_end=end,
            status="RUNNING",
        )
        self.db.add(run)
        self.db.commit()
        self.run_id = run.id

        try:
            warehouses = list(self.db.scalars(select(Warehouse).order_by(Warehouse.id)).all())
            skus = list(self.db.scalars(select(SKU).order_by(SKU.id)).all())
            suppliers = {s.id: s for s in self.db.scalars(select(Supplier)).all()}

            inventory = {(w.id, s.id): self.rng.randint(70, 150) for w in warehouses for s in skus}
            backorders = defaultdict(int)
            on_order = defaultdict(int)
            arrivals: dict[date, list[ScheduledReceipt]] = defaultdict(list)
            po_sequence = 0

            for offset in range(days):
                day_number = offset + 1
                day = start + timedelta(days=offset)
                ts = datetime.combine(day, time(9))
                scenario_active = self._active(scenario, day_number)

                if scenario_active and scenario and scenario.scenario_type == "warehouse_shutdown":
                    for warehouse in warehouses:
                        if self._matches(scenario, warehouse_id=warehouse.id):
                            self._add_event(
                                event_time=ts,
                                event_type=WAREHOUSE_SHUTDOWN,
                                warehouse_id=warehouse.id,
                                reference=scenario.id,
                                details={"scenario_id": scenario.id, "day_number": day_number},
                            )

                if (
                    scenario_active
                    and scenario
                    and scenario.scenario_type == "inventory_loss"
                    and day_number == scenario.start_day
                ):
                    for warehouse in warehouses:
                        for sku in skus:
                            if not self._matches(
                                scenario,
                                warehouse_id=warehouse.id,
                                supplier_id=sku.supplier_id,
                                sku_id=sku.id,
                            ):
                                continue
                            key = (warehouse.id, sku.id)
                            lost = min(inventory[key], int(inventory[key] * scenario.inventory_loss_pct))
                            inventory[key] -= lost
                            self._add_event(
                                event_time=ts,
                                event_type=INVENTORY_LOSS,
                                warehouse_id=warehouse.id,
                                supplier_id=sku.supplier_id,
                                sku_id=sku.id,
                                quantity=lost,
                                reference=scenario.id,
                                details={"inventory_loss_pct": scenario.inventory_loss_pct},
                            )

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

                for warehouse in warehouses:
                    for sku in skus:
                        key = (warehouse.id, sku.id)
                        demand = max(0, int(self.rng.gauss(7 + sku.id % 5, 3)))
                        matches = bool(
                            scenario
                            and scenario_active
                            and self._matches(
                                scenario,
                                warehouse_id=warehouse.id,
                                supplier_id=sku.supplier_id,
                                sku_id=sku.id,
                            )
                        )
                        if matches and scenario and scenario.scenario_type == "demand_spike":
                            baseline_demand = demand
                            demand = int(round(demand * scenario.demand_multiplier))
                            self._add_event(
                                event_time=ts,
                                event_type=DEMAND_SPIKE,
                                warehouse_id=warehouse.id,
                                supplier_id=sku.supplier_id,
                                sku_id=sku.id,
                                quantity=demand - baseline_demand,
                                reference=scenario.id,
                                details={"demand_multiplier": scenario.demand_multiplier},
                            )

                        warehouse_closed = bool(matches and scenario and scenario.scenario_type == "warehouse_shutdown")
                        available = 0 if warehouse_closed else inventory[key]
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

                        if shortage and not warehouse_closed:
                            donor = max(
                                (candidate for candidate in warehouses if candidate.id != warehouse.id),
                                key=lambda candidate: inventory[(candidate.id, sku.id)],
                            )
                            donor_key = (donor.id, sku.id)
                            transferable = max(0, inventory[donor_key] - sku.reorder_point)
                            transfer_qty = min(shortage, transferable)
                            if transfer_qty:
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
                                    },
                                )
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
                        if inventory_position <= sku.reorder_point and not warehouse_closed:
                            supplier = suppliers[sku.supplier_id]
                            po_sequence += 1
                            po_reference = f"PO-{day:%Y%m%d}-{po_sequence:05d}"
                            reliability_draw = self.rng.random()
                            random_delay = 0 if reliability_draw <= supplier.reliability else self.rng.randint(1, 4)

                            if matches and scenario and scenario.scenario_type == "supplier_shutdown":
                                self._add_event(
                                    event_time=ts,
                                    event_type=SUPPLIER_SHUTDOWN,
                                    warehouse_id=warehouse.id,
                                    sku_id=sku.id,
                                    supplier_id=supplier.id,
                                    quantity=sku.reorder_qty,
                                    reference=scenario.id,
                                    details={"blocked_purchase_order": po_reference},
                                )
                                continue

                            order_qty = sku.reorder_qty
                            lead_time = supplier.base_lead_time_days
                            extra_delay = 0
                            if matches and scenario and scenario.scenario_type == "supplier_capacity_reduction":
                                order_qty = int(round(order_qty * (1 - scenario.capacity_reduction_pct)))
                                self._add_event(
                                    event_time=ts,
                                    event_type=CAPACITY_REDUCTION,
                                    warehouse_id=warehouse.id,
                                    sku_id=sku.id,
                                    supplier_id=supplier.id,
                                    quantity=sku.reorder_qty - order_qty,
                                    reference=scenario.id,
                                    details={"capacity_reduction_pct": scenario.capacity_reduction_pct},
                                )
                            if matches and scenario and scenario.scenario_type == "lead_time_increase":
                                original_lead_time = lead_time
                                lead_time = math.ceil(lead_time * scenario.lead_time_multiplier)
                                self._add_event(
                                    event_time=ts,
                                    event_type=LEAD_TIME_INCREASE,
                                    warehouse_id=warehouse.id,
                                    sku_id=sku.id,
                                    supplier_id=supplier.id,
                                    quantity=lead_time - original_lead_time,
                                    reference=scenario.id,
                                    details={"lead_time_multiplier": scenario.lead_time_multiplier},
                                )
                            if matches and scenario and scenario.scenario_type == "transportation_delay":
                                extra_delay = scenario.delay_days
                                self._add_event(
                                    event_time=ts,
                                    event_type=TRANSPORTATION_DELAY,
                                    warehouse_id=warehouse.id,
                                    sku_id=sku.id,
                                    supplier_id=supplier.id,
                                    quantity=order_qty,
                                    reference=scenario.id,
                                    details={"delay_days": extra_delay},
                                )

                            if order_qty > 0:
                                arrival_date = day + timedelta(days=lead_time + random_delay + extra_delay)
                                arrivals[arrival_date].append(
                                    ScheduledReceipt(
                                        warehouse_id=warehouse.id,
                                        sku_id=sku.id,
                                        supplier_id=supplier.id,
                                        quantity=order_qty,
                                        purchase_order_reference=po_reference,
                                    )
                                )
                                on_order[key] += order_qty
                                self._add_event(
                                    event_time=ts,
                                    event_type=PURCHASE_ORDER_CREATED,
                                    warehouse_id=warehouse.id,
                                    sku_id=sku.id,
                                    supplier_id=supplier.id,
                                    quantity=order_qty,
                                    cost=Decimal("35.00"),
                                    reference=po_reference,
                                    details={
                                        "expected_arrival_date": arrival_date.isoformat(),
                                        "delay_days": random_delay + extra_delay,
                                    },
                                )
                                if random_delay:
                                    self._add_event(
                                        event_time=ts,
                                        event_type=SUPPLIER_DELAY,
                                        warehouse_id=warehouse.id,
                                        sku_id=sku.id,
                                        supplier_id=supplier.id,
                                        quantity=order_qty,
                                        reference=po_reference,
                                        details={
                                            "delay_days": random_delay,
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
                                run_id=self.run_id,
                                snapshot_date=day,
                                warehouse_id=warehouse.id,
                                sku_id=sku.id,
                                on_hand=inventory[key],
                                on_order=on_order[key],
                                backorder=backorders[key],
                            )
                        )
                self.db.commit()

            refresh_analytics(self.db, self.run_id)
            run.status = "COMPLETED"
            run.completed_at = utc_now()
            self.db.commit()
            return {
                "run_id": run.id,
                "run_type": run.run_type,
                "scenario_id": run.scenario_id,
                "baseline_run_id": run.baseline_run_id,
                "days": days,
                "seed": self.seed,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "status": run.status,
            }
        except Exception as exc:
            self.db.rollback()
            failed_run = self.db.get(SimulationRun, run.id)
            if failed_run:
                failed_run.status = "FAILED"
                failed_run.error_message = str(exc)[:2000]
                failed_run.completed_at = utc_now()
                self.db.commit()
            raise

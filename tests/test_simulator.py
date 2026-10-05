from decimal import Decimal

from sqlalchemy import func, select

from app.db.models import SKU, DailyNetworkKPI, InventorySnapshot, SimulationRun, SupplyChainEvent, Warehouse
from app.simulator.engine import DigitalTwinSimulator
from app.simulator.events import (
    BACKORDER_CREATED,
    BACKORDER_FULFILLED,
    PURCHASE_ORDER_CREATED,
    SHIPMENT_RECEIVED,
    SUPPLIER_DELAY,
)


def test_simulation_builds_expected_dimensions_and_facts(db):
    result = DigitalTwinSimulator(db, seed=42).run(days=5)
    run_id = result["run_id"]
    assert result["days"] == 5
    assert result["seed"] == 42
    assert result["status"] == "COMPLETED"
    assert db.scalar(select(func.count()).select_from(Warehouse)) == 3
    assert db.scalar(select(func.count()).select_from(SKU)) == 30
    assert db.scalar(
        select(func.count()).select_from(InventorySnapshot).where(InventorySnapshot.run_id == run_id)
    ) == 3 * 30 * 5
    assert db.scalar(
        select(func.count()).select_from(SupplyChainEvent).where(SupplyChainEvent.run_id == run_id)
    ) > 0
    assert db.scalar(
        select(func.count()).select_from(DailyNetworkKPI).where(DailyNetworkKPI.run_id == run_id)
    ) == 5


def test_simulation_is_deterministic_and_preserves_both_runs(db):
    simulator = DigitalTwinSimulator(db, seed=7)
    first_result = simulator.run(days=10)
    first = [
        (x.kpi_date, x.demand_units, x.fulfilled_units, round(x.fill_rate, 6), float(x.total_cost))
        for x in db.scalars(
            select(DailyNetworkKPI)
            .where(DailyNetworkKPI.run_id == first_result["run_id"])
            .order_by(DailyNetworkKPI.kpi_date)
        )
    ]
    second_result = simulator.run(days=10)
    second = [
        (x.kpi_date, x.demand_units, x.fulfilled_units, round(x.fill_rate, 6), float(x.total_cost))
        for x in db.scalars(
            select(DailyNetworkKPI)
            .where(DailyNetworkKPI.run_id == second_result["run_id"])
            .order_by(DailyNetworkKPI.kpi_date)
        )
    ]
    assert first_result["run_id"] != second_result["run_id"]
    assert first == second
    assert db.scalar(select(func.count()).select_from(SimulationRun)) == 2


def test_inventory_snapshots_track_on_order_and_backorders(db):
    result = DigitalTwinSimulator(db, seed=42).run(days=30)
    run_id = result["run_id"]
    assert db.scalar(
        select(func.max(InventorySnapshot.on_order)).where(InventorySnapshot.run_id == run_id)
    ) > 0
    assert db.scalar(
        select(func.max(InventorySnapshot.backorder)).where(InventorySnapshot.run_id == run_id)
    ) >= 0

    created = db.scalar(
        select(func.coalesce(func.sum(SupplyChainEvent.quantity), 0)).where(
            SupplyChainEvent.run_id == run_id,
            SupplyChainEvent.event_type == BACKORDER_CREATED,
        )
    )
    fulfilled = db.scalar(
        select(func.coalesce(func.sum(SupplyChainEvent.quantity), 0)).where(
            SupplyChainEvent.run_id == run_id,
            SupplyChainEvent.event_type == BACKORDER_FULFILLED,
        )
    )
    ending_backorder = db.scalar(
        select(func.coalesce(func.sum(InventorySnapshot.backorder), 0)).where(
            InventorySnapshot.run_id == run_id,
            InventorySnapshot.snapshot_date
            == select(func.max(InventorySnapshot.snapshot_date))
            .where(InventorySnapshot.run_id == run_id)
            .scalar_subquery(),
        )
    )
    assert int(created or 0) == int(fulfilled or 0) + int(ending_backorder or 0)


def test_purchase_orders_are_not_duplicated_while_inventory_is_inbound(db):
    result = DigitalTwinSimulator(db, seed=42).run(days=30)
    run_id = result["run_id"]
    purchase_orders = list(
        db.scalars(
            select(SupplyChainEvent)
            .where(
                SupplyChainEvent.run_id == run_id,
                SupplyChainEvent.event_type == PURCHASE_ORDER_CREATED,
            )
            .order_by(SupplyChainEvent.warehouse_id, SupplyChainEvent.sku_id, SupplyChainEvent.event_time)
        )
    )
    assert purchase_orders
    assert len({event.reference for event in purchase_orders}) == len(purchase_orders)

    received_references = set(
        db.scalars(
            select(SupplyChainEvent.reference).where(
                SupplyChainEvent.run_id == run_id,
                SupplyChainEvent.event_type == SHIPMENT_RECEIVED,
            )
        )
    )
    po_references = {event.reference for event in purchase_orders}
    assert received_references <= po_references


def test_supplier_delay_events_have_supplier_and_delay_details(db):
    result = DigitalTwinSimulator(db, seed=42).run(days=30)
    delays = list(
        db.scalars(
            select(SupplyChainEvent).where(
                SupplyChainEvent.run_id == result["run_id"],
                SupplyChainEvent.event_type == SUPPLIER_DELAY,
            )
        )
    )
    assert delays
    assert all(event.supplier_id is not None for event in delays)
    assert all(event.details and "delay_days" in event.details for event in delays)


def test_network_cost_equals_sum_of_cost_components(db):
    result = DigitalTwinSimulator(db, seed=42).run(days=10)
    for kpi in db.scalars(
        select(DailyNetworkKPI).where(DailyNetworkKPI.run_id == result["run_id"])
    ):
        expected = kpi.holding_cost + kpi.ordering_cost + kpi.transfer_cost + kpi.shortage_cost
        assert Decimal(kpi.total_cost) == Decimal(expected)

from datetime import date

import pytest
from sqlalchemy import func, select

from app.db.models import DailyNetworkKPI, SupplyChainEvent
from app.simulator.disruptions import DemandSpike, DisruptionConfig, SupplierShutdown, TransferDelay
from app.simulator.engine import DigitalTwinSimulator
from app.simulator.events import DEMAND_CREATED, STOCKOUT, SUPPLIER_DELAY


def test_demand_spike_increases_demand(db):
    baseline_sim = DigitalTwinSimulator(db, seed=42)
    baseline_sim.run(days=10, reset=True)
    baseline_demand = int(
        db.scalar(
            select(func.sum(SupplyChainEvent.quantity)).where(SupplyChainEvent.event_type == DEMAND_CREATED)
        )
        or 0
    )

    disruptions = DisruptionConfig(
        demand_spikes=[
            DemandSpike(
                multiplier=3.0,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 10),
            )
        ]
    )
    disrupted_sim = DigitalTwinSimulator(db, seed=42, disruptions=disruptions)
    disrupted_sim.run(days=10, reset=True)
    disrupted_demand = int(
        db.scalar(
            select(func.sum(SupplyChainEvent.quantity)).where(SupplyChainEvent.event_type == DEMAND_CREATED)
        )
        or 0
    )

    assert disrupted_demand > baseline_demand, "Demand spike should increase total demand"


def test_demand_spike_increases_stockouts(db):
    disruptions = DisruptionConfig(
        demand_spikes=[
            DemandSpike(
                multiplier=5.0,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 10),
            )
        ]
    )
    DigitalTwinSimulator(db, seed=42).run(days=10, reset=True)
    baseline_stockout = int(
        db.scalar(
            select(func.sum(SupplyChainEvent.quantity)).where(SupplyChainEvent.event_type == STOCKOUT)
        )
        or 0
    )

    DigitalTwinSimulator(db, seed=42, disruptions=disruptions).run(days=10, reset=True)
    disrupted_stockout = int(
        db.scalar(
            select(func.sum(SupplyChainEvent.quantity)).where(SupplyChainEvent.event_type == STOCKOUT)
        )
        or 0
    )
    assert disrupted_stockout >= baseline_stockout


def test_supplier_shutdown_generates_delay_events(db):
    disruptions = DisruptionConfig(
        supplier_shutdowns=[
            SupplierShutdown(
                supplier_id=1,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 10),
            )
        ]
    )
    DigitalTwinSimulator(db, seed=42, disruptions=disruptions).run(days=10)
    shutdown_events = list(
        db.scalars(
            select(SupplyChainEvent).where(
                SupplyChainEvent.event_type == SUPPLIER_DELAY,
                SupplyChainEvent.supplier_id == 1,
            )
        ).all()
    )
    assert any("supplier_shutdown" in (e.details or "") for e in shutdown_events), (
        "Expected at least one supplier_shutdown delay event for supplier 1"
    )


def test_transfer_delay_does_not_crash(db):
    disruptions = DisruptionConfig(
        transfer_delays=[
            TransferDelay(extra_days=2, start_date=date(2026, 1, 1), end_date=date(2026, 1, 30))
        ]
    )
    result = DigitalTwinSimulator(db, seed=42, disruptions=disruptions).run(days=10)
    assert result["days"] == 10


def test_disruption_config_demand_multiplier_targeting():
    cfg = DisruptionConfig(
        demand_spikes=[
            DemandSpike(multiplier=2.0, start_date=date(2026, 1, 3), end_date=date(2026, 1, 5), sku_ids=[1])
        ]
    )
    assert cfg.demand_multiplier(date(2026, 1, 3), sku_id=1, warehouse_id=1) == 2.0
    assert cfg.demand_multiplier(date(2026, 1, 3), sku_id=2, warehouse_id=1) == 1.0
    assert cfg.demand_multiplier(date(2026, 1, 2), sku_id=1, warehouse_id=1) == 1.0


def test_disruption_config_supplier_shutdown_check():
    cfg = DisruptionConfig(
        supplier_shutdowns=[
            SupplierShutdown(supplier_id=2, start_date=date(2026, 1, 5), end_date=date(2026, 1, 8))
        ]
    )
    assert cfg.is_supplier_shutdown(date(2026, 1, 6), 2) is True
    assert cfg.is_supplier_shutdown(date(2026, 1, 4), 2) is False
    assert cfg.is_supplier_shutdown(date(2026, 1, 6), 1) is False


def test_disruption_config_transfer_extra_days():
    cfg = DisruptionConfig(
        transfer_delays=[
            TransferDelay(extra_days=3, start_date=date(2026, 1, 5), end_date=date(2026, 1, 10))
        ]
    )
    assert cfg.transfer_extra_days(date(2026, 1, 7)) == 3
    assert cfg.transfer_extra_days(date(2026, 1, 4)) == 0

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    region: Mapped[str] = mapped_column(String(50))

    inventory_snapshots: Mapped[list[InventorySnapshot]] = relationship(back_populates="warehouse")
    events: Mapped[list[SupplyChainEvent]] = relationship(back_populates="warehouse")
    daily_kpis: Mapped[list[DailyWarehouseKPI]] = relationship(back_populates="warehouse")


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    base_lead_time_days: Mapped[int] = mapped_column(Integer)
    reliability: Mapped[float] = mapped_column(Float)

    skus: Mapped[list[SKU]] = relationship(back_populates="supplier")
    events: Mapped[list[SupplyChainEvent]] = relationship(back_populates="supplier")


class SKU(Base):
    __tablename__ = "skus"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(120))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    holding_cost_daily: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    shortage_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    reorder_point: Mapped[int] = mapped_column(Integer)
    reorder_qty: Mapped[int] = mapped_column(Integer)

    supplier: Mapped[Supplier] = relationship(back_populates="skus")
    inventory_snapshots: Mapped[list[InventorySnapshot]] = relationship(back_populates="sku")
    events: Mapped[list[SupplyChainEvent]] = relationship(back_populates="sku")


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_type: Mapped[str] = mapped_column(String(20), default="baseline", index=True)
    baseline_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    scenario_name: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    seed: Mapped[int] = mapped_column(Integer)
    simulation_start: Mapped[date] = mapped_column(Date)
    simulation_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    inventory_snapshots: Mapped[list[InventorySnapshot]] = relationship(back_populates="run")
    events: Mapped[list[SupplyChainEvent]] = relationship(back_populates="run")
    warehouse_kpis: Mapped[list[DailyWarehouseKPI]] = relationship(back_populates="run")
    network_kpis: Mapped[list[DailyNetworkKPI]] = relationship(back_populates="run")


class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshots"
    __table_args__ = (UniqueConstraint("run_id", "snapshot_date", "warehouse_id", "sku_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.id"), index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), index=True)
    on_hand: Mapped[int] = mapped_column(Integer)
    on_order: Mapped[int] = mapped_column(Integer, default=0)
    backorder: Mapped[int] = mapped_column(Integer, default=0)

    run: Mapped[SimulationRun] = relationship(back_populates="inventory_snapshots")
    warehouse: Mapped[Warehouse] = relationship(back_populates="inventory_snapshots")
    sku: Mapped[SKU] = relationship(back_populates="inventory_snapshots")


class SupplyChainEvent(Base):
    __tablename__ = "supply_chain_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.id"), index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True, index=True)
    sku_id: Mapped[int | None] = mapped_column(ForeignKey("skus.id"), nullable=True, index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True, index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[str | None] = mapped_column(String(500), nullable=True)

    run: Mapped[SimulationRun] = relationship(back_populates="events")
    warehouse: Mapped[Warehouse | None] = relationship(back_populates="events")
    sku: Mapped[SKU | None] = relationship(back_populates="events")
    supplier: Mapped[Supplier | None] = relationship(back_populates="events")


class DailyWarehouseKPI(Base):
    __tablename__ = "daily_warehouse_kpis"
    __table_args__ = (UniqueConstraint("run_id", "kpi_date", "warehouse_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.id"), index=True)
    kpi_date: Mapped[date] = mapped_column(Date, index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), index=True)
    demand_units: Mapped[int] = mapped_column(Integer)
    fulfilled_units: Mapped[int] = mapped_column(Integer)
    stockout_units: Mapped[int] = mapped_column(Integer)
    fill_rate: Mapped[float] = mapped_column(Float)
    inventory_units: Mapped[int] = mapped_column(Integer)
    inventory_value: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    holding_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    ordering_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    transfer_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    shortage_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    run: Mapped[SimulationRun] = relationship(back_populates="warehouse_kpis")
    warehouse: Mapped[Warehouse] = relationship(back_populates="daily_kpis")


class DailyNetworkKPI(Base):
    __tablename__ = "daily_network_kpis"
    __table_args__ = (UniqueConstraint("run_id", "kpi_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.id"), index=True)
    kpi_date: Mapped[date] = mapped_column(Date, index=True)
    demand_units: Mapped[int] = mapped_column(Integer)
    fulfilled_units: Mapped[int] = mapped_column(Integer)
    stockout_units: Mapped[int] = mapped_column(Integer)
    fill_rate: Mapped[float] = mapped_column(Float)
    inventory_units: Mapped[int] = mapped_column(Integer)
    inventory_value: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    holding_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    ordering_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    transfer_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    shortage_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    run: Mapped[SimulationRun] = relationship(back_populates="network_kpis")


class ScenarioRun(Base):
    __tablename__ = "scenario_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    days: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    baseline_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    scenario_run_id: Mapped[str] = mapped_column(String(36), index=True)
    disruption_config: Mapped[str | None] = mapped_column(Text, nullable=True)
    delta_fill_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta_total_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    delta_stockout_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recovery_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kpi_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)

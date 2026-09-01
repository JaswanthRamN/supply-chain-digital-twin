from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


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


class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshots"
    __table_args__ = (UniqueConstraint("snapshot_date", "warehouse_id", "sku_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), index=True)
    on_hand: Mapped[int] = mapped_column(Integer)
    on_order: Mapped[int] = mapped_column(Integer, default=0)
    backorder: Mapped[int] = mapped_column(Integer, default=0)

    warehouse: Mapped[Warehouse] = relationship(back_populates="inventory_snapshots")
    sku: Mapped[SKU] = relationship(back_populates="inventory_snapshots")


class SupplyChainEvent(Base):
    __tablename__ = "supply_chain_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True, index=True)
    sku_id: Mapped[int | None] = mapped_column(ForeignKey("skus.id"), nullable=True, index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True, index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[str | None] = mapped_column(String(500), nullable=True)

    warehouse: Mapped[Warehouse | None] = relationship(back_populates="events")
    sku: Mapped[SKU | None] = relationship(back_populates="events")
    supplier: Mapped[Supplier | None] = relationship(back_populates="events")


class DailyWarehouseKPI(Base):
    __tablename__ = "daily_warehouse_kpis"
    __table_args__ = (UniqueConstraint("kpi_date", "warehouse_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
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

    warehouse: Mapped[Warehouse] = relationship(back_populates="daily_kpis")


class DailyNetworkKPI(Base):
    __tablename__ = "daily_network_kpis"

    kpi_date: Mapped[date] = mapped_column(Date, primary_key=True)
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


class ScenarioRun(Base):
    __tablename__ = "scenario_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    days: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    disruption_config: Mapped[str | None] = mapped_column(Text, nullable=True)
    # KPI deltas vs baseline (populated by scenario comparison)
    delta_fill_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta_total_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    delta_stockout_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Serialised daily network KPIs snapshot for this scenario
    kpi_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)

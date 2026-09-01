from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class WarehouseOut(_ORM):
    id: int
    code: str
    name: str
    region: str


class SupplierOut(_ORM):
    id: int
    code: str
    name: str
    base_lead_time_days: int
    reliability: float


class SKUOut(_ORM):
    id: int
    code: str
    description: str
    supplier_id: int
    unit_cost: Decimal
    holding_cost_daily: Decimal
    shortage_cost: Decimal
    reorder_point: int
    reorder_qty: int


class DimensionsOut(BaseModel):
    warehouses: list[WarehouseOut]
    suppliers: list[SupplierOut]
    skus: list[SKUOut]


class InventorySnapshotOut(_ORM):
    id: int
    snapshot_date: date
    warehouse_id: int
    sku_id: int
    on_hand: int
    on_order: int
    backorder: int


class LowStockAlertOut(BaseModel):
    warehouse_id: int
    sku_id: int
    sku_code: str
    on_hand: int
    reorder_point: int
    shortfall: int


class SupplyChainEventOut(_ORM):
    id: int
    event_time: datetime
    event_type: str
    warehouse_id: int | None
    sku_id: int | None
    supplier_id: int | None
    quantity: int
    cost: Decimal
    reference: str | None
    details: str | None


class NetworkKPIOut(_ORM):
    kpi_date: date
    demand_units: int
    fulfilled_units: int
    stockout_units: int
    fill_rate: float
    inventory_units: int
    inventory_value: Decimal
    holding_cost: Decimal
    ordering_cost: Decimal
    transfer_cost: Decimal
    shortage_cost: Decimal
    total_cost: Decimal


class WarehouseKPIOut(_ORM):
    id: int
    kpi_date: date
    warehouse_id: int
    demand_units: int
    fulfilled_units: int
    stockout_units: int
    fill_rate: float
    inventory_units: int
    inventory_value: Decimal
    holding_cost: Decimal
    ordering_cost: Decimal
    transfer_cost: Decimal
    shortage_cost: Decimal
    total_cost: Decimal


class SKUKPIOut(BaseModel):
    sku_id: int
    sku_code: str
    description: str
    total_stockout_units: int
    total_shortage_cost: Decimal
    total_demand_units: int
    fill_rate: float


class SupplierKPIOut(BaseModel):
    supplier_id: int
    supplier_code: str
    name: str
    total_purchase_orders: int
    total_delays: int
    delay_rate: float
    avg_delay_days: float


class SimulationResult(BaseModel):
    days: int
    seed: int
    start_date: date
    end_date: date


# ── Scenario / Disruption schemas ──────────────────────────────────────────

class SupplierShutdownIn(BaseModel):
    supplier_id: int
    start_date: date
    end_date: date


class DemandSpikeIn(BaseModel):
    multiplier: float = Field(gt=0)
    start_date: date
    end_date: date
    sku_ids: list[int] = Field(default_factory=list)
    warehouse_ids: list[int] = Field(default_factory=list)


class TransferDelayIn(BaseModel):
    extra_days: int = Field(ge=1)
    start_date: date
    end_date: date


class ScenarioRequest(BaseModel):
    name: str
    days: int = Field(30, ge=1, le=365)
    seed: int = 42
    start_date: date = date(2026, 1, 1)
    compare_to_baseline: bool = True
    supplier_shutdowns: list[SupplierShutdownIn] = Field(default_factory=list)
    demand_spikes: list[DemandSpikeIn] = Field(default_factory=list)
    transfer_delays: list[TransferDelayIn] = Field(default_factory=list)


class ScenarioRunOut(_ORM):
    id: int
    name: str
    created_at: datetime
    days: int
    seed: int
    start_date: date
    end_date: date
    disruption_config: str | None
    delta_fill_rate: float | None
    delta_total_cost: Decimal | None
    delta_stockout_units: int | None
    kpi_snapshot: str | None

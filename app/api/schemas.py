from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


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

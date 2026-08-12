from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScenarioType(StrEnum):
    DEMAND_SPIKE = "demand_spike"
    SUPPLIER_SHUTDOWN = "supplier_shutdown"
    SUPPLIER_CAPACITY_REDUCTION = "supplier_capacity_reduction"
    LEAD_TIME_INCREASE = "lead_time_increase"
    TRANSPORTATION_DELAY = "transportation_delay"
    WAREHOUSE_SHUTDOWN = "warehouse_shutdown"
    INVENTORY_LOSS = "inventory_loss"


class ScenarioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    scenario_type: ScenarioType
    description: str | None = Field(default=None, max_length=2000)
    start_day: int = Field(default=1, ge=1)
    end_day: int = Field(default=1, ge=1)
    warehouse_id: int | None = Field(default=None, ge=1)
    supplier_id: int | None = Field(default=None, ge=1)
    sku_id: int | None = Field(default=None, ge=1)
    demand_multiplier: float = Field(default=1.0, gt=0)
    lead_time_multiplier: float = Field(default=1.0, gt=0)
    capacity_reduction_pct: float = Field(default=0.0, ge=0, le=1)
    delay_days: int = Field(default=0, ge=0)
    inventory_loss_pct: float = Field(default=0.0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_scenario(self):
        if self.end_day < self.start_day:
            raise ValueError("end_day must be greater than or equal to start_day")
        if self.scenario_type == ScenarioType.DEMAND_SPIKE and self.demand_multiplier <= 1:
            raise ValueError("demand_multiplier must be greater than 1 for demand_spike")
        if self.scenario_type == ScenarioType.SUPPLIER_CAPACITY_REDUCTION:
            if not 0 < self.capacity_reduction_pct <= 1:
                raise ValueError("capacity_reduction_pct must be greater than 0")
        if self.scenario_type == ScenarioType.LEAD_TIME_INCREASE and self.lead_time_multiplier <= 1:
            raise ValueError("lead_time_multiplier must be greater than 1 for lead_time_increase")
        if self.scenario_type == ScenarioType.TRANSPORTATION_DELAY and self.delay_days < 1:
            raise ValueError("delay_days must be at least 1 for transportation_delay")
        if self.scenario_type == ScenarioType.INVENTORY_LOSS and not 0 < self.inventory_loss_pct <= 1:
            raise ValueError("inventory_loss_pct must be greater than 0")
        if self.scenario_type in {
            ScenarioType.SUPPLIER_SHUTDOWN,
            ScenarioType.SUPPLIER_CAPACITY_REDUCTION,
            ScenarioType.LEAD_TIME_INCREASE,
        } and self.supplier_id is None:
            raise ValueError("supplier_id is required for supplier disruptions")
        if self.scenario_type == ScenarioType.WAREHOUSE_SHUTDOWN and self.warehouse_id is None:
            raise ValueError("warehouse_id is required for warehouse_shutdown")
        return self


class ScenarioRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(default=30, ge=1, le=365)
    seed: int = 42
    start_date: date = date(2026, 1, 1)


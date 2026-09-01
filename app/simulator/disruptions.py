from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal


@dataclass
class SupplierShutdown:
    """Block a supplier from fulfilling purchase orders for a date window."""
    supplier_id: int
    start_date: date
    end_date: date


@dataclass
class DemandSpike:
    """Multiply demand for specific SKUs/warehouses by a factor for a date window."""
    multiplier: float
    start_date: date
    end_date: date
    sku_ids: list[int] = field(default_factory=list)    # empty = all SKUs
    warehouse_ids: list[int] = field(default_factory=list)  # empty = all warehouses


@dataclass
class TransferDelay:
    """Add extra lead-time days to all inter-warehouse transfers."""
    extra_days: int
    start_date: date
    end_date: date


@dataclass
class DisruptionConfig:
    """Collection of disruptions applied during a scenario simulation run."""
    supplier_shutdowns: list[SupplierShutdown] = field(default_factory=list)
    demand_spikes: list[DemandSpike] = field(default_factory=list)
    transfer_delays: list[TransferDelay] = field(default_factory=list)

    def demand_multiplier(self, sim_date: date, sku_id: int, warehouse_id: int) -> float:
        """Return the combined demand multiplier for a given date/sku/warehouse."""
        multiplier = 1.0
        for spike in self.demand_spikes:
            if spike.start_date <= sim_date <= spike.end_date:
                if (not spike.sku_ids or sku_id in spike.sku_ids) and (
                    not spike.warehouse_ids or warehouse_id in spike.warehouse_ids
                ):
                    multiplier *= spike.multiplier
        return multiplier

    def is_supplier_shutdown(self, sim_date: date, supplier_id: int) -> bool:
        """Return True if the supplier is shut down on this date."""
        return any(
            s.supplier_id == supplier_id and s.start_date <= sim_date <= s.end_date
            for s in self.supplier_shutdowns
        )

    def transfer_extra_days(self, sim_date: date) -> int:
        """Return total extra transfer delay days active on this date."""
        return sum(
            d.extra_days
            for d in self.transfer_delays
            if d.start_date <= sim_date <= d.end_date
        )

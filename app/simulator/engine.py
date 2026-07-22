from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import random
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.db.models import InventorySnapshot, SKU, Supplier, SupplyChainEvent, Warehouse
from app.analytics.refresh import refresh_analytics

class DigitalTwinSimulator:
    def __init__(self, db: Session, seed: int = 42):
        self.db = db
        self.rng = random.Random(seed)

    def seed_master_data(self) -> None:
        if self.db.scalar(select(Warehouse.id).limit(1)):
            return
        warehouses = [Warehouse(code=f"WH{i}", name=n, region=r) for i,(n,r) in enumerate([
            ("East Distribution Center","East"),("Central Distribution Center","Central"),("West Distribution Center","West")],1)]
        suppliers = [Supplier(code=f"SUP{i:02d}", name=f"Supplier {i}", base_lead_time_days=2+i, reliability=0.82+i*0.03) for i in range(1,6)]
        self.db.add_all(warehouses + suppliers); self.db.flush()
        for i in range(1,31):
            supplier = suppliers[(i-1) % 5]
            self.db.add(SKU(code=f"SKU-{i:03d}", description=f"Component {i}", supplier_id=supplier.id,
                unit_cost=Decimal(str(8 + i*1.35)), holding_cost_daily=Decimal("0.04"), shortage_cost=Decimal("7.50"),
                reorder_point=35 + (i % 6)*5, reorder_qty=80 + (i % 5)*10))
        self.db.commit()

    def reset_operational_data(self) -> None:
        self.db.execute(delete(InventorySnapshot)); self.db.execute(delete(SupplyChainEvent)); self.db.commit()

    def run(self, days: int = 30, start_date: date | None = None, reset: bool = True) -> dict:
        self.seed_master_data()
        if reset: self.reset_operational_data()
        start = start_date or date(2026, 1, 1)
        warehouses = self.db.scalars(select(Warehouse)).all(); skus = self.db.scalars(select(SKU)).all()
        inventory = {(w.id,s.id): self.rng.randint(70,150) for w in warehouses for s in skus}
        arrivals: dict[date, list[tuple[int,int,int]]] = defaultdict(list)
        for offset in range(days):
            day = start + timedelta(days=offset); ts = datetime.combine(day, time(9))
            for wh_id, sku_id, qty in arrivals.pop(day, []):
                inventory[(wh_id,sku_id)] += qty
                self.db.add(SupplyChainEvent(event_time=ts,event_type="RECEIPT",warehouse_id=wh_id,sku_id=sku_id,quantity=qty,cost=0))
            for wh in warehouses:
                for sku in skus:
                    demand = max(0, int(self.rng.gauss(7 + sku.id % 5, 3)))
                    available = inventory[(wh.id,sku.id)]; fulfilled = min(available,demand); shortage = demand-fulfilled
                    inventory[(wh.id,sku.id)] -= fulfilled
                    self.db.add(SupplyChainEvent(event_time=ts,event_type="DEMAND",warehouse_id=wh.id,sku_id=sku.id,quantity=demand,cost=0))
                    self.db.add(SupplyChainEvent(event_time=ts,event_type="FULFILLMENT",warehouse_id=wh.id,sku_id=sku.id,quantity=fulfilled,cost=0))
                    if shortage:
                        donor = max((x for x in warehouses if x.id != wh.id), key=lambda x: inventory[(x.id,sku.id)])
                        transfer = min(shortage, max(0, inventory[(donor.id,sku.id)]-sku.reorder_point))
                        if transfer:
                            inventory[(donor.id,sku.id)] -= transfer; inventory[(wh.id,sku.id)] += transfer
                            delivered = min(transfer, shortage); inventory[(wh.id,sku.id)] -= delivered; fulfilled += delivered; shortage -= delivered
                            self.db.add(SupplyChainEvent(event_time=ts,event_type="TRANSFER",warehouse_id=wh.id,sku_id=sku.id,quantity=transfer,cost=Decimal("2.00")*transfer,reference=f"FROM-{donor.code}"))
                            self.db.add(SupplyChainEvent(event_time=ts,event_type="FULFILLMENT",warehouse_id=wh.id,sku_id=sku.id,quantity=delivered,cost=0,reference="TRANSFER"))
                        if shortage:
                            self.db.add(SupplyChainEvent(event_time=ts,event_type="STOCKOUT",warehouse_id=wh.id,sku_id=sku.id,quantity=shortage,cost=sku.shortage_cost*shortage))
                    if inventory[(wh.id,sku.id)] <= sku.reorder_point:
                        supplier = self.db.get(Supplier, sku.supplier_id)
                        delay = 0 if self.rng.random() <= supplier.reliability else self.rng.randint(1,4)
                        arrival = day + timedelta(days=supplier.base_lead_time_days + delay)
                        arrivals[arrival].append((wh.id,sku.id,sku.reorder_qty))
                        self.db.add(SupplyChainEvent(event_time=ts,event_type="PURCHASE_ORDER",warehouse_id=wh.id,sku_id=sku.id,quantity=sku.reorder_qty,cost=Decimal("35.00"),reference=arrival.isoformat()))
                    holding = sku.holding_cost_daily * inventory[(wh.id,sku.id)]
                    self.db.add(SupplyChainEvent(event_time=ts,event_type="HOLDING_COST",warehouse_id=wh.id,sku_id=sku.id,quantity=inventory[(wh.id,sku.id)],cost=holding))
                    self.db.add(InventorySnapshot(snapshot_date=day,warehouse_id=wh.id,sku_id=sku.id,on_hand=inventory[(wh.id,sku.id)],on_order=0,backorder=shortage))
            self.db.commit()
        refresh_analytics(self.db)
        return {"days": days, "start_date": start.isoformat(), "end_date": (start+timedelta(days=days-1)).isoformat()}

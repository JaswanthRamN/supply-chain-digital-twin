# Milestone 7 — Baseline Stabilization Progress

## Objective

Replace the compact Version 2 prototype with a maintainable, testable baseline before building the disruption and scenario engine.

## Completed in this branch

- Added SQLAlchemy relationships for warehouses, suppliers, SKUs, inventory snapshots, events, and warehouse KPIs.
- Added supplier linkage to operational events.
- Added indexed foreign keys used by common analytics and API filters.
- Expanded network KPI storage to preserve holding, ordering, transfer, and shortage cost components.
- Added a canonical `EventType` enum to remove inconsistent event names across simulation, analytics, API, and dashboard code.

## Next implementation steps

1. Replace the compressed simulator with explicit inventory, backorder, purchase-order, receipt, and transfer lifecycle logic.
2. Prevent duplicate replenishment orders by using inventory position: on hand + on order - backorders.
3. Track open orders and actual on-order quantities.
4. Carry backorders forward and fulfill them after inventory receipts.
5. Record supplier-delay events and standardized shipment-receipt events.
6. Refactor KPI calculations into reusable analytics functions.
7. Add Pydantic request and response schemas.
8. Expand API filtering, validation, and error handling.
9. Add regression tests for every corrected business rule.
10. Run deterministic SQLite verification and document Docker/PostgreSQL limitations separately.

## Milestone boundary

No Milestone 8 scenario behavior will be added until the stabilized baseline passes the expanded test suite and the comparison against the original Version 2 prototype is documented.

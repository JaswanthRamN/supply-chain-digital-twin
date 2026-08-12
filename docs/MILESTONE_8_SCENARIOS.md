# Milestone 8 — Disruption and Scenario Engine

Milestone 8 adds persistent, deterministic scenario analysis without overwriting prior simulation results.

## Scenario lifecycle

1. Create a scenario with `POST /scenarios`.
2. Execute a controlled baseline/scenario pair with `POST /scenarios/{scenario_id}/runs`.
3. Inspect history with `GET /runs` and results with `GET /runs/{run_id}/results`.
4. Retrieve baseline-versus-scenario metrics with `GET /runs/{scenario_run_id}/comparison`.

Scenario and simulation-run IDs are server-generated UUIDs. A scenario execution creates two immutable runs with the same seed, simulation start date, and duration. The scenario run stores its `baseline_run_id` so the comparison remains reproducible.

## Supported disruptions

| `scenario_type` | Required parameters | Effect |
| --- | --- | --- |
| `demand_spike` | `demand_multiplier > 1` | Multiplies demand for matching targets. |
| `supplier_shutdown` | `supplier_id` | Blocks matching replenishment orders. |
| `supplier_capacity_reduction` | `supplier_id`, `capacity_reduction_pct` | Reduces matching replenishment quantities. |
| `lead_time_increase` | `supplier_id`, `lead_time_multiplier > 1` | Increases matching supplier lead time. |
| `transportation_delay` | `delay_days >= 1` | Adds days to matching inbound shipments. |
| `warehouse_shutdown` | `warehouse_id` | Prevents fulfillment and replenishment at the warehouse. |
| `inventory_loss` | `inventory_loss_pct` | Removes matching inventory once at scenario start. |

Targets may include `warehouse_id`, `supplier_id`, and `sku_id`. `start_day` and `end_day` are inclusive, one-based offsets within the requested simulation window. Omitted optional targets make the disruption global within the applicable dimension.

## Example

```bash
curl -X POST http://localhost:8000/scenarios \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "East warehouse demand surge",
    "scenario_type": "demand_spike",
    "start_day": 5,
    "end_day": 12,
    "warehouse_id": 1,
    "demand_multiplier": 1.75
  }'

curl -X POST http://localhost:8000/scenarios/SCENARIO_ID/runs \
  -H 'Content-Type: application/json' \
  -d '{"days": 30, "seed": 42, "start_date": "2026-01-01"}'
```

## Comparison definitions

- Demand, fulfilled units, stockouts, and total cost are summed over the run.
- Fill rate is total fulfilled units divided by total demand units.
- Inventory is the average daily network inventory.
- Delta is `scenario - baseline`.
- Percentage change is `delta / baseline * 100`; it is `null` when the baseline is zero.
- Recovery days is the first day after the disruption window where scenario fill rate reaches that day's baseline fill rate. It is `null` if recovery is not observed.

## Persistence and schema note

Operational facts and KPI tables are keyed by `run_id`; executing a new run never deletes previous runs. Milestone 8 changes the database schema, so existing development databases created before this milestone must be migrated or recreated before starting the application.

## Verification

Run the complete regression suite:

```bash
pytest -q
```

Coverage includes deterministic repeated runs, unique IDs, multiple-run preservation, every disruption type and its target, request validation, run history, result retrieval, comparison arithmetic, zero-baseline handling, and the end-to-end scenario lifecycle.


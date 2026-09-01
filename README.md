# AI-Powered Supply Chain Digital Twin

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/JaswanthRamN/supply-chain-digital-twin/actions/workflows/ci.yml/badge.svg)](https://github.com/JaswanthRamN/supply-chain-digital-twin/actions/workflows/ci.yml)

A deterministic supply-chain simulation and operations analytics platform for three warehouses, 30 SKUs, and five suppliers. Includes a Milestone 8 disruption and scenario engine for what-if analysis.

## Architecture

1. **Simulation engine** generates demand, fulfillment, stockouts, transfers, purchase orders, receipts, and costs. Accepts a `DisruptionConfig` for supplier shutdowns, demand spikes, and transfer delays.
2. **Operational store** uses SQLAlchemy and supports PostgreSQL in Docker plus SQLite for local development/tests.
3. **Analytics layer** materialises daily warehouse and network KPI tables.
4. **FastAPI service** exposes inventory, events, dimensions, simulation controls, KPI endpoints, low-stock alerts, and scenario comparison.
5. **Operations Control Tower** is a Streamlit dashboard with fill rate trends, per-warehouse charts, SKU stockout heatmaps, supplier performance, low-stock alerts, and a built-in scenario runner.

## Quick start with Docker Compose

```bash
cp .env.example .env          # edit passwords if needed
docker compose up --build
```

- API docs: http://localhost:8000/docs
- Control Tower: http://localhost:8501

Seed data:

```bash
curl -X POST 'http://localhost:8000/simulation/run?days=30'
```

## Local development with SQLite

```bash
make install          # pip install -r requirements.txt
python -m scripts.run_simulation --days 30
make dev              # uvicorn with --reload
make dashboard        # streamlit run
```

Or step-by-step:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.run_simulation --days 30
uvicorn app.main:app --reload
streamlit run dashboard/control_tower.py
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/simulation/run` | Run a baseline simulation |
| `POST` | `/simulation/scenario` | Run a disruption scenario and compare to baseline |
| `GET`  | `/simulation/scenarios` | List all scenario runs |
| `GET`  | `/simulation/scenarios/{id}` | Get a single scenario run |
| `GET`  | `/inventory` | Inventory snapshots (filterable, paginated) |
| `GET`  | `/inventory/low-stock` | Items at or below reorder point |
| `GET`  | `/events` | Supply-chain events (filterable, paginated) |
| `GET`  | `/kpis/summary` | Latest network KPI snapshot |
| `GET`  | `/kpis/network` | Daily network KPI series |
| `GET`  | `/kpis/warehouse` | Daily per-warehouse KPIs |
| `GET`  | `/kpis/sku` | Per-SKU stockout and fill-rate summary |
| `GET`  | `/kpis/supplier` | Per-supplier delay rate and average delay days |
| `GET`  | `/dimensions` | Warehouses, suppliers, and SKUs |

Full interactive docs: http://localhost:8000/docs

## Disruption scenarios

```bash
curl -X POST http://localhost:8000/simulation/scenario \
  -H "Content-Type: application/json" \
  -d '{
    "name": "supplier-1-shutdown",
    "days": 30,
    "seed": 42,
    "start_date": "2026-01-01",
    "compare_to_baseline": true,
    "supplier_shutdowns": [
      {"supplier_id": 1, "start_date": "2026-01-10", "end_date": "2026-01-20"}
    ],
    "demand_spikes": [],
    "transfer_delays": []
  }'
```

Supported disruption types:
- **`supplier_shutdowns`** — block a supplier from fulfilling POs for a date window
- **`demand_spikes`** — multiply demand for specific SKUs/warehouses by a factor
- **`transfer_delays`** — add extra lead-time days to inter-warehouse transfers

Response includes `delta_fill_rate`, `delta_total_cost`, and `delta_stockout_units` vs the baseline.

## Analytics tables

- `daily_warehouse_kpis`: daily demand, fulfilled units, stockouts, fill rate, inventory, inventory value, and cost components by warehouse.
- `daily_network_kpis`: consolidated daily network metrics.
- `scenario_runs`: named scenario results with KPI deltas and a daily snapshot.

## Development

```bash
make test    # pytest -q
make lint    # ruff check .
```

## Tests

```bash
pytest -q
```

38 tests covering simulation, disruption engine, all API endpoints, and edge cases.

## License

This project is licensed under the [MIT License](LICENSE).

Copyright (c) 2026 Jaswanth Ram Nagabhyrava.

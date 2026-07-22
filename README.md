# AI-Powered Supply Chain Digital Twin

A deterministic supply-chain simulation and operations analytics platform for three warehouses, 30 SKUs, and five suppliers.

## Architecture

1. **Simulation engine** generates demand, fulfillment, stockouts, transfers, purchase orders, receipts, and costs.
2. **Operational store** uses SQLAlchemy and supports PostgreSQL in Docker plus SQLite for local development/tests.
3. **Analytics layer** materializes daily warehouse and network KPI tables.
4. **FastAPI service** exposes inventory, events, dimensions, simulation controls, and KPI endpoints.
5. **Operations Control Tower** is a Streamlit dashboard for fill rate, inventory, demand, costs, warehouse performance, and recent exceptions.

## Run with Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

- API docs: http://localhost:8000/docs
- Control Tower: http://localhost:8501

Create data:

```bash
curl -X POST 'http://localhost:8000/simulation/run?days=30'
```

## Run locally with SQLite

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.run_simulation --days 30
uvicorn app.main:app --reload
streamlit run dashboard/control_tower.py
```

## Analytics tables

- `daily_warehouse_kpis`: daily demand, fulfilled units, stockouts, fill rate, inventory, inventory value, and cost components by warehouse.
- `daily_network_kpis`: consolidated daily network metrics.

## Tests

```bash
pytest -q
```

## License

This project is licensed under the [MIT License](LICENSE).

Copyright (c) 2026 Jaswanth Ram Nagabhyrava.

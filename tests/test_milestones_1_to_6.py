from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

import yaml
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.core.config import Settings
from app.db.base import Base
from app.db.models import DailyNetworkKPI, InventorySnapshot, SimulationRun, SupplyChainEvent
from app.db.session import get_db
from app.main import app
from app.simulator.engine import DigitalTwinSimulator


ROOT = Path(__file__).resolve().parents[1]


def test_milestone_1_repository_and_runtime_foundation():
    required = {
        "README.md",
        "LICENSE",
        "requirements.txt",
        "Dockerfile",
        "docker-compose.yml",
        ".env.example",
        "app/main.py",
    }
    assert all((ROOT / path).is_file() for path in required)
    assert "MIT License" in (ROOT / "LICENSE").read_text()
    assert "AI-Powered Supply Chain Digital Twin" in (ROOT / "README.md").read_text()

    requirements = {
        line.split("==", 1)[0].split("[", 1)[0]
        for line in (ROOT / "requirements.txt").read_text().splitlines()
        if line and not line.startswith("#")
    }
    assert {"fastapi", "sqlalchemy", "psycopg", "streamlit", "pytest"} <= requirements


def test_milestone_2_database_schema_and_postgres_compatibility(db):
    table_names = set(inspect(db.get_bind()).get_table_names())
    assert {
        "warehouses",
        "suppliers",
        "skus",
        "simulation_runs",
        "inventory_snapshots",
        "supply_chain_events",
        "daily_warehouse_kpis",
        "daily_network_kpis",
    } <= table_names

    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert f"CREATE TABLE {table.name}" in ddl

    sqlite = Settings(database_url="sqlite:///test.db")
    postgres = Settings(database_url="postgresql+psycopg://user:pass@db:5432/supply_chain")
    assert sqlite.database_url.startswith("sqlite")
    assert postgres.database_url.startswith("postgresql+psycopg")


def test_milestone_3_simulation_and_analytics_are_complete(db):
    result = DigitalTwinSimulator(db, seed=123).run(days=4)
    run_id = result["run_id"]

    assert result["status"] == "COMPLETED"
    assert len(db.scalars(select(InventorySnapshot).where(InventorySnapshot.run_id == run_id)).all()) == 4 * 3 * 30
    assert len(db.scalars(select(DailyNetworkKPI).where(DailyNetworkKPI.run_id == run_id)).all()) == 4
    assert db.scalar(select(SupplyChainEvent.id).where(SupplyChainEvent.run_id == run_id).limit(1)) is not None

    for row in db.scalars(select(DailyNetworkKPI).where(DailyNetworkKPI.run_id == run_id)):
        assert 0 <= row.fill_rate <= 1
        assert row.demand_units == row.fulfilled_units + row.stockout_units
        assert row.total_cost == row.holding_cost + row.ordering_cost + row.transfer_cost + row.shortage_cost


def test_milestone_4_api_contract_and_cli_workflow(db, tmp_path):
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            assert client.get("/health").json() == {"status": "ok"}
            schema = client.get("/openapi.json")
            assert schema.status_code == 200
            assert {
                "/simulation/run",
                "/inventory",
                "/events",
                "/kpis/summary",
                "/kpis/network",
                "/kpis/warehouse",
                "/dimensions",
            } <= set(schema.json()["paths"])
    finally:
        app.dependency_overrides.clear()

    database_path = tmp_path / "cli.db"
    env = os.environ | {"DATABASE_URL": f"sqlite:///{database_path}"}
    initialized = subprocess.run(
        [sys.executable, "-m", "scripts.init_db"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert initialized.returncode == 0, initialized.stderr
    assert "Database initialized" in initialized.stdout

    simulated = subprocess.run(
        [sys.executable, "-m", "scripts.run_simulation", "--days", "1", "--seed", "9"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert simulated.returncode == 0, simulated.stderr
    assert "'status': 'COMPLETED'" in simulated.stdout
    assert database_path.exists()


def test_milestone_5_dashboard_and_container_topology():
    dashboard_path = ROOT / "dashboard/control_tower.py"
    dashboard_source = dashboard_path.read_text()
    ast.parse(dashboard_source)
    assert "Operations Control Tower" in dashboard_source
    assert all(
        endpoint in dashboard_source
        for endpoint in ("/kpis/summary", "/kpis/network", "/kpis/warehouse", "/dimensions", "/events")
    )
    assert ".metric(" in dashboard_source
    assert all(component in dashboard_source for component in ("st.plotly_chart", "st.dataframe"))

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert set(compose["services"]) == {"db", "api", "dashboard"}
    assert compose["services"]["db"]["healthcheck"]
    assert compose["services"]["api"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert compose["services"]["dashboard"]["depends_on"] == ["api"]
    assert "postgresql+psycopg" in compose["services"]["api"]["environment"]["DATABASE_URL"]

    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "FROM python:3.12-slim" in dockerfile
    assert 'CMD ["uvicorn"' in dockerfile


def test_milestone_6_clean_startup_and_repeatable_baseline(db):
    first = DigitalTwinSimulator(db, seed=2026).run(days=3)
    second = DigitalTwinSimulator(db, seed=2026).run(days=3)
    assert first["run_id"] != second["run_id"]

    first_kpis = [
        (row.kpi_date, row.demand_units, row.fulfilled_units, row.stockout_units, row.fill_rate, row.total_cost)
        for row in db.scalars(
            select(DailyNetworkKPI)
            .where(DailyNetworkKPI.run_id == first["run_id"])
            .order_by(DailyNetworkKPI.kpi_date)
        )
    ]
    second_kpis = [
        (row.kpi_date, row.demand_units, row.fulfilled_units, row.stockout_units, row.fill_rate, row.total_cost)
        for row in db.scalars(
            select(DailyNetworkKPI)
            .where(DailyNetworkKPI.run_id == second["run_id"])
            .order_by(DailyNetworkKPI.kpi_date)
        )
    ]
    assert first_kpis == second_kpis
    assert db.scalar(select(SimulationRun.id).where(SimulationRun.id == first["run_id"]))
    assert db.scalar(select(SimulationRun.id).where(SimulationRun.id == second["run_id"]))

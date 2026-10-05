from sqlalchemy import inspect

from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.session import engine


def init_db() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    legacy_operational_tables = {
        "inventory_snapshots",
        "supply_chain_events",
        "daily_warehouse_kpis",
        "daily_network_kpis",
    }
    if tables & legacy_operational_tables and "simulation_runs" not in tables:
        raise RuntimeError(
            "Pre-Milestone-8B database schema detected. "
            "Run-scoped history adds simulation_runs and run_id columns. "
            "Because the current project uses synthetic data and Alembic is not yet configured, "
            "recreate the local database or Docker volume before starting this branch."
        )

    Base.metadata.create_all(bind=engine)

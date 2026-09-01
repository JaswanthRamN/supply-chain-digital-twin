import typer

from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.simulator.engine import DigitalTwinSimulator

app = typer.Typer()


@app.command()
def run(days: int = 30, seed: int = 42):
    init_db()
    with SessionLocal() as db:
        print(DigitalTwinSimulator(db, seed).run(days=days))


if __name__ == "__main__":
    app()

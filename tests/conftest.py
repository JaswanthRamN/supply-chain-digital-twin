import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.base import Base

@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread":False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        yield s

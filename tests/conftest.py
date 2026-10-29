"""Pruebas de Fleet con SQLite en memoria (sin PostgreSQL)."""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite://"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app import models  # noqa: F401

# SQLite no tiene secuencias: se quitan solo en las pruebas los defaults 'nextval'
for _tabla in Base.metadata.tables.values():
    for _col in _tabla.columns:
        if _col.server_default is not None and "nextval" in str(getattr(_col.server_default, "arg", "")):
            _col.server_default = None


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sesion = sessionmaker(bind=engine, autoflush=False)()
    yield sesion
    sesion.close()
    engine.dispose()


@pytest.fixture()
def api(db):
    def _get_db():
        yield db
    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()

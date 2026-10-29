"""/health: lo usan Render y el pipeline de despliegue para comprobar que la versión nueva quedó viva."""
from fastapi.testclient import TestClient

from app.main import app

CLIENTE = TestClient(app)


def test_health_devuelve_la_version_de_la_imagen(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "abc1234")
    r = CLIENTE.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "fleet-service", "version": "abc1234"}


def test_health_sin_version_configurada_indica_dev(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    assert CLIENTE.get("/health").json()["version"] == "dev"


def test_health_no_exige_la_clave_interna(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "clave-de-prueba-123")
    assert CLIENTE.get("/health").status_code == 200

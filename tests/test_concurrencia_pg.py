"""Escenario D: concurrencia REAL contra PostgreSQL (hilos + transacciones independientes).
Se omite si no hay una base disponible: defina TEST_PG_URL=postgresql+psycopg2://usuario:clave@host/base_vacia."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

URL = os.getenv("TEST_PG_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_PG_URL no definida: prueba de concurrencia en PostgreSQL omitida")

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Reserva, Vehiculo  # noqa: E402
from utiles import BOGOTA, GIRARDOT, MONTERIA, origen, vehiculo  # noqa: E402


@pytest.fixture()
def pg():
    engine = create_engine(URL, pool_size=20, max_overflow=20)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    base_sesion = sessionmaker(bind=engine, autoflush=False)
    abiertas = []

    def Sesion():  # las sesiones de las pruebas se cierran al terminar para no retener bloqueos
        s = base_sesion()
        abiertas.append(s)
        return s

    def _get_db():
        s = Sesion()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _get_db
    yield Sesion
    app.dependency_overrides.clear()
    for s in abiertas:
        s.close()
    engine.dispose()


def _paralelo(n, funcion):
    with ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(funcion, range(n)))


def _post(ruta, cuerpo):
    return TestClient(app).post(ruta, json=cuerpo)


def test_ocho_peticiones_simultaneas_y_tres_vehiculos_solo_tres_ganan(pg):
    s = pg()
    for punto in (BOGOTA, GIRARDOT, MONTERIA):
        vehiculo(s, capacidad=1000, ubicacion=punto)
    resp = _paralelo(8, lambda i: _post("/reservas/", {"envio_id": str(uuid.uuid4()), "peso_kg": 100, "origen": origen(BOGOTA)}))
    codigos = sorted(r.status_code for r in resp)
    assert codigos == [201] * 3 + [409] * 5, codigos
    s = pg()
    activas = s.query(Reserva).filter(Reserva.estado == "reservada").all()
    assert len({r.vehiculo_id for r in activas}) == 3  # ningún vehículo asignado dos veces


def test_cargas_compartidas_simultaneas_nunca_superan_la_capacidad(pg):
    s = pg()
    v = vehiculo(s, capacidad=1000, ubicacion=BOGOTA)
    base = _post("/reservas/", {"envio_id": str(uuid.uuid4()), "peso_kg": 100, "origen": origen(BOGOTA)})
    assert base.status_code == 201
    resp = _paralelo(12, lambda i: _post("/reservas/compartida", {"envio_id": str(uuid.uuid4()), "vehiculo_id": str(v.id), "peso_kg": 200}))
    ok = [r for r in resp if r.status_code == 201]
    assert len(ok) == 4, sorted(r.status_code for r in resp)  # 100 + 4*200 = 900 <= 1000; una quinta daría 1100
    assert all(r.status_code == 409 and r.json()["detail"]["codigo"] == "CAPACIDAD_EXCEDIDA" for r in resp if r.status_code != 201)
    s = pg()
    f = s.get(Vehiculo, v.id)
    suma = sum(float(r.peso_kg) for r in s.query(Reserva).filter(Reserva.vehiculo_id == v.id, Reserva.estado == "reservada"))
    assert float(f.peso_reservado_kg) == suma == 900


def test_el_mismo_envio_enviado_en_paralelo_crea_una_sola_reserva(pg):
    s = pg()
    v = vehiculo(s, capacidad=1000, ubicacion=BOGOTA)
    _post("/reservas/", {"envio_id": str(uuid.uuid4()), "peso_kg": 100, "origen": origen(BOGOTA)})
    envio = str(uuid.uuid4())
    resp = _paralelo(10, lambda i: _post("/reservas/compartida", {"envio_id": envio, "vehiculo_id": str(v.id), "peso_kg": 150}))
    assert sorted({r.status_code for r in resp}) <= [200, 201] and sum(r.status_code == 201 for r in resp) == 1
    s = pg()
    assert s.query(Reserva).filter(Reserva.envio_id == uuid.UUID(envio)).count() == 1
    assert float(s.get(Vehiculo, v.id).peso_reservado_kg) == 250


def test_reservar_exclusivo_el_mismo_envio_en_paralelo_no_duplica(pg):
    s = pg()
    vehiculo(s, capacidad=1000, ubicacion=BOGOTA)
    vehiculo(s, capacidad=1000, ubicacion=GIRARDOT)
    envio = str(uuid.uuid4())
    resp = _paralelo(10, lambda i: _post("/reservas/", {"envio_id": envio, "peso_kg": 100, "origen": origen(BOGOTA)}))
    assert {r.status_code for r in resp} <= {200, 201} and sum(r.status_code == 201 for r in resp) == 1
    assert len({r.json()["vehiculo"]["id"] for r in resp}) == 1
    s = pg()
    assert s.query(Reserva).filter(Reserva.estado == "reservada").count() == 1


def test_liberar_y_compartir_a_la_vez_dejan_los_contadores_consistentes(pg):
    s = pg()
    v = vehiculo(s, capacidad=1000, ubicacion=BOGOTA)
    envios = [str(uuid.uuid4()) for _ in range(6)]
    assert _post("/reservas/", {"envio_id": envios[0], "peso_kg": 100, "origen": origen(BOGOTA)}).status_code == 201

    def tarea(i):
        if i % 2:
            return _post("/reservas/compartida", {"envio_id": envios[i], "vehiculo_id": str(v.id), "peso_kg": 100})
        return _post("/reservas/liberar", {"envio_id": envios[i]})

    _paralelo(6, tarea)
    conc = TestClient(app).post("/reservas/conciliar")
    assert conc.status_code == 200
    s = pg()
    f = s.get(Vehiculo, v.id)
    suma = sum(float(r.peso_kg) for r in s.query(Reserva).filter(Reserva.vehiculo_id == v.id, Reserva.estado == "reservada"))
    assert float(f.peso_reservado_kg) == suma
    assert 0 <= float(f.peso_reservado_kg) <= float(f.capacidad_kg)


def test_el_check_de_la_base_impide_sobrepasar_la_capacidad_aunque_falle_la_logica(pg):
    s = pg()
    v = vehiculo(s, capacidad=500, ubicacion=BOGOTA)
    with pytest.raises(Exception):
        s.execute(text("update vehiculos set peso_reservado_kg = 501 where id = :i"), {"i": v.id})
        s.commit()

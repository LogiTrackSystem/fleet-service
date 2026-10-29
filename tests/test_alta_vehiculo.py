"""Alta de vehículos: la ubicación base es obligatoria y el carro nuevo queda listo para asignarse."""
import uuid

import pytest

from app.models import Conductor, Vehiculo
from utiles import BOGOTA, CALI, MONTERIA, reservar, vehiculo


def cuerpo(placa="KQA794", punto=BOGOTA, nombre="Bogotá", **extra):
    return {
        "placa": placa, "tipo": "camion", "capacidad_kg": 5000, "anio": 2022,
        "ubicacion_id": str(uuid.uuid4()), "ubicacion_nombre": nombre,
        "latitud": punto[0], "longitud": punto[1], "codigo_pais": punto[2], **extra,
    }


def vincular_conductor(db, v):
    n = abs(hash(v.placa)) % 100000
    db.add(Conductor(id=uuid.uuid4(), codigo_conductor=n, nombre="Conductor", licencia_numero=f"LIC{n}",
                     categorias_licencia="C2", anios_experiencia=8, vehiculo_id=v.id, estado="available"))
    db.commit()


def test_el_vehiculo_nace_con_su_ubicacion_confiable(api):
    r = api.post("/vehiculos/", json=cuerpo())
    assert r.status_code == 201
    d = r.json()
    assert (d["latitud"], d["longitud"], d["codigo_pais"]) == (4.711, -74.0721, "CO")
    assert d["ubicacion_nombre"] == "Bogotá" and d["ubicacion_fuente"] == "registro_gestor"
    assert d["ubicacion_confiable"] is True and d["ubicacion_actualizada_en"] is not None
    assert api.get("/vehiculos/placa/KQA794").json()["latitud"] == 4.711


@pytest.mark.parametrize("campo", ["ubicacion_id", "ubicacion_nombre", "latitud", "longitud", "codigo_pais"])
def test_sin_ubicacion_no_se_crea_el_vehiculo(api, db, campo):
    c = cuerpo()
    c.pop(campo)
    r = api.post("/vehiculos/", json=c)
    assert r.status_code == 422 and campo in r.text
    assert db.query(Vehiculo).count() == 0


@pytest.mark.parametrize("cambio", [
    {"latitud": 91}, {"latitud": -91}, {"longitud": 181}, {"longitud": -181}, {"codigo_pais": "COL"}, {"codigo_pais": "C"},
    {"ubicacion_nombre": "   "}, {"ubicacion_id": "no-es-uuid"}, {"latitud": None},
])
def test_ubicacion_invalida_se_rechaza(api, db, cambio):
    assert api.post("/vehiculos/", json=cuerpo(**cambio)).status_code == 422
    assert db.query(Vehiculo).count() == 0


def test_el_pais_se_normaliza_y_la_placa_repetida_sigue_dando_409(api):
    assert api.post("/vehiculos/", json=cuerpo(punto=(4.711, -74.0721, "co"))).json()["codigo_pais"] == "CO"
    r = api.post("/vehiculos/", json=cuerpo())
    assert r.status_code == 409


def test_el_vehiculo_nuevo_se_asigna_de_inmediato_por_cercania(api, db):
    lejano = vehiculo(db, ubicacion=MONTERIA, placa="LEJ001")
    nuevo = api.post("/vehiculos/", json=cuerpo(placa="KQA794")).json()
    vincular_conductor(db, db.query(Vehiculo).filter(Vehiculo.placa == "KQA794").one())
    r = reservar(api, peso=100, punto=BOGOTA)
    assert r.status_code == 201, r.text
    assert r.json()["vehiculo"]["id"] == nuevo["id"]    # estaba en Bogotá; el otro en Montería
    assert r.json()["decision"]["sin_ubicacion_fiable"] is False and r.json()["reposicion"]["distancia_linea_recta_km"] == 0.0
    assert r.json()["vehiculo"]["id"] != str(lejano.id)


def test_la_ubicacion_de_un_vehiculo_existente_se_corrige_con_la_misma_lista(api, db):
    """Vehículos creados antes de este cambio (sin ubicación): se fijan con PUT /ubicacion usando la ubicación elegida."""
    v = vehiculo(db)
    assert api.get(f"/vehiculos/{v.id}").json()["ubicacion_confiable"] is False
    r = api.put(f"/vehiculos/{v.id}/ubicacion", json={
        "ubicacion_id": str(uuid.uuid4()), "nombre": "Cali", "latitud": CALI[0], "longitud": CALI[1], "codigo_pais": "CO",
        "fuente": "registro_gestor"})
    assert r.status_code == 200 and r.json()["aplicada"] is True
    d = api.get(f"/vehiculos/{v.id}").json()
    assert d["ubicacion_confiable"] is True and d["ubicacion_nombre"] == "Cali" and d["latitud"] == 3.4516

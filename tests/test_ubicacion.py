"""Última ubicación real del vehículo: se conserva, no retrocede y no se inventa."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Vehiculo
from utiles import BOGOTA, CALI, MONTERIA, reservar, vehiculo


def _put(api, v, punto, **extra):
    cuerpo = {"latitud": punto[0], "longitud": punto[1], "codigo_pais": punto[2], **extra}
    return api.put(f"/vehiculos/{v.id}/ubicacion", json=cuerpo)


def test_un_vehiculo_nuevo_no_tiene_ubicacion_y_no_se_inventa_ninguna(api, db):
    v = vehiculo(db)
    r = api.get(f"/vehiculos/{v.id}").json()
    assert r["latitud"] is None and r["ubicacion_confiable"] is False


def test_el_gestor_fija_la_ubicacion_base_y_queda_fiable(api, db):
    v = vehiculo(db)
    r = _put(api, v, MONTERIA, nombre="Montería", fuente="registro_gestor")
    assert r.status_code == 200 and r.json()["aplicada"] is True
    datos = api.get(f"/vehiculos/{v.id}").json()
    assert (datos["latitud"], datos["codigo_pais"], datos["ubicacion_confiable"]) == (8.748, "CO", True)
    assert datos["ubicacion_fuente"] == "registro_gestor"


def test_una_posicion_mas_antigua_nunca_pisa_a_la_mas_reciente(api, db):
    v = vehiculo(db)
    ahora = datetime.now(timezone.utc)
    _put(api, v, CALI, tomada_en=ahora.isoformat(), fuente="entrega")
    r = _put(api, v, MONTERIA, tomada_en=(ahora - timedelta(hours=3)).isoformat(), fuente="entrega")
    assert r.status_code == 200
    assert r.json()["aplicada"] is False and r.json()["motivo"] == "UBICACION_MAS_RECIENTE_YA_REGISTRADA"
    assert api.get(f"/vehiculos/{v.id}").json()["latitud"] == 3.4516  # sigue en Cali


def test_reintentar_la_misma_posicion_es_idempotente(api, db):
    v = vehiculo(db)
    momento = datetime.now(timezone.utc).isoformat()
    assert _put(api, v, BOGOTA, tomada_en=momento, fuente="entrega").json()["aplicada"] is True
    assert _put(api, v, BOGOTA, tomada_en=momento, fuente="entrega").json()["aplicada"] is True
    assert api.get(f"/vehiculos/{v.id}").json()["latitud"] == 4.711


def test_coordenadas_fuera_de_rango_se_rechazan(api, db):
    v = vehiculo(db)
    assert api.put(f"/vehiculos/{v.id}/ubicacion", json={"latitud": 95, "longitud": 0}).status_code == 422
    assert api.put(f"/vehiculos/{v.id}/ubicacion", json={"latitud": 0, "longitud": -181}).status_code == 422


def test_vehiculo_inexistente_da_404(api):
    assert api.put(f"/vehiculos/{uuid.uuid4()}/ubicacion", json={"latitud": 1, "longitud": 1}).status_code == 404


def test_reservar_deja_la_posicion_anterior_en_la_respuesta_y_deja_de_ser_fiable(api, db):
    v = vehiculo(db, ubicacion=CALI)
    r = reservar(api, peso=100, punto=CALI)
    assert r.status_code == 201, r.text
    desde = r.json()["reposicion"]["desde"]
    assert desde["latitud"] == 3.4516 and desde["codigo_pais"] == "CO" and desde["fiable"] is True
    assert r.json()["reposicion"]["aproximacion"] == "linea_recta"
    db.expire_all()
    assert db.get(Vehiculo, v.id).ubicacion_confiable is False  # se va a mover: ya no vale como "dónde está"


def test_tras_liberar_la_ubicacion_vieja_no_se_usa_hasta_que_tracking_informe_la_nueva(api, db):
    v = vehiculo(db, ubicacion=MONTERIA)
    r = reservar(api, punto=MONTERIA).json()
    api.post("/reservas/liberar", json={"envio_id": r["envio_id"]})
    db.expire_all()
    assert db.get(Vehiculo, v.id).ubicacion_confiable is False
    # Tracking informa dónde terminó el viaje (Cali) y entonces vuelve a ser fiable
    assert _put(api, v, CALI, fuente="entrega").json()["aplicada"] is True
    db.expire_all()
    f = db.get(Vehiculo, v.id)
    assert f.ubicacion_confiable is True and float(f.latitud) == 3.4516


def test_el_gestor_no_puede_fijar_la_posicion_con_el_vehiculo_en_viaje_pero_tracking_si(api, db):
    v = vehiculo(db, ubicacion=MONTERIA)
    reservar(api, punto=MONTERIA)
    r = _put(api, v, CALI, fuente="registro_gestor")
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "VEHICULO_EN_VIAJE"
    assert _put(api, v, CALI, fuente="entrega").status_code == 200


def test_no_se_puede_bajar_la_capacidad_por_debajo_de_lo_reservado(api, db):
    v = vehiculo(db, capacidad=1000)
    reservar(api, peso=600)
    r = api.patch(f"/vehiculos/{v.id}", json={"capacidad_kg": 500})
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "CAPACIDAD_MENOR_A_LA_RESERVADA"
    assert api.patch(f"/vehiculos/{v.id}", json={"capacidad_kg": 800}).status_code == 200


def test_tracking_puede_devolver_la_ubicacion_original_tras_un_viaje_cancelado_antes_de_salir(api, db):
    v = vehiculo(db, ubicacion=CALI)
    db.refresh(v)
    original = v.ubicacion_actualizada_en
    r = reservar(api, punto=BOGOTA).json()
    desde = r["reposicion"]["desde"]
    api.post("/reservas/liberar", json={"envio_id": r["envio_id"]})
    db.expire_all()
    assert db.get(Vehiculo, v.id).ubicacion_confiable is False
    resp = api.put(f"/vehiculos/{v.id}/ubicacion", json={
        "latitud": desde["latitud"], "longitud": desde["longitud"], "codigo_pais": desde["codigo_pais"],
        "tomada_en": desde["tomada_en"], "fuente": "interrupcion"})
    assert resp.json()["aplicada"] is True
    db.expire_all()
    assert db.get(Vehiculo, v.id).ubicacion_confiable is True and float(db.get(Vehiculo, v.id).latitud) == 3.4516


def test_un_reenvio_tardio_de_la_misma_posicion_no_devuelve_la_confianza_a_un_vehiculo_que_ya_salio(api, db):
    v = vehiculo(db, ubicacion=CALI)
    db.refresh(v)
    r = reservar(api, punto=BOGOTA).json()
    desde = r["reposicion"]["desde"]
    cuerpo = {"latitud": desde["latitud"], "longitud": desde["longitud"], "codigo_pais": desde["codigo_pais"],
              "tomada_en": desde["tomada_en"], "fuente": "interrupcion"}
    resp = api.put(f"/vehiculos/{v.id}/ubicacion", json=cuerpo)   # el vehículo está reservado (en viaje)
    assert resp.json()["aplicada"] is False and resp.json()["motivo"] == "VEHICULO_RESERVADO_POSICION_YA_REGISTRADA"
    db.expire_all()
    assert db.get(Vehiculo, v.id).ubicacion_confiable is False   # sigue sin ser una posición real vigente

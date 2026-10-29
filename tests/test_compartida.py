"""Escenario B (lado Fleet): carga compartida sin sobreasignar peso, volumen ni mezclar cargas incompatibles."""
import uuid

from app.models import Vehiculo
from utiles import BOGOTA, compartir, reservar, vehiculo


def _con_viaje(api, db, capacidad=1000, m3=None, peso=300, vol=None, tipo_carga=None, es_hazmat=False, **kw):
    v = vehiculo(db, capacidad=capacidad, m3=m3, ubicacion=BOGOTA, **kw)
    extra = {"volumen_m3": vol} if vol else {}
    if tipo_carga:
        extra["tipo_carga"] = tipo_carga
    if es_hazmat:
        extra["es_hazmat"] = True
    r = reservar(api, peso=peso, punto=BOGOTA, **extra)
    assert r.status_code == 201, r.text
    return v, r.json()


def test_una_segunda_carga_comparte_el_vehiculo_si_cabe(api, db):
    v, base = _con_viaje(api, db, capacidad=1000, peso=300)
    r = compartir(api, v.id, peso=500)
    assert r.status_code == 201, r.text
    assert r.json()["modo"] == "compartida" and r.json()["conductor"]["id"] == base["conductor"]["id"]
    assert r.json()["ocupacion"]["peso_reservado_kg"] == 800 and r.json()["ocupacion"]["peso_disponible_kg"] == 200


def test_peso_que_no_cabe_se_rechaza_y_no_cambia_nada(api, db):
    v, _ = _con_viaje(api, db, capacidad=1000, peso=800)
    r = compartir(api, v.id, peso=300)
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "CAPACIDAD_EXCEDIDA"
    assert api.get(f"/vehiculos/{v.id}/ocupacion").json()["peso_reservado_kg"] == 800


def test_el_volumen_tambien_limita(api, db):
    v, _ = _con_viaje(api, db, capacidad=5000, m3=10, peso=100, vol=7)
    r = compartir(api, v.id, peso=100, volumen_m3=4)
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "VOLUMEN_EXCEDIDO"
    assert compartir(api, v.id, peso=100, volumen_m3=3).status_code == 201


def test_hazmat_es_exclusivo_en_ambos_sentidos(api, db):
    v, _ = _con_viaje(api, db, hazmat=True, peso=100, es_hazmat=True)
    r = compartir(api, v.id, peso=100)
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "HAZMAT_NO_COMPARTE"
    w, _ = _con_viaje(api, db, hazmat=True, peso=100)
    r2 = compartir(api, w.id, peso=100, es_hazmat=True)
    assert r2.status_code == 409 and r2.json()["detail"]["codigo"] == "HAZMAT_NO_COMPARTE"


def test_refrigerada_y_general_no_se_mezclan_pero_dos_refrigeradas_si(api, db):
    v, _ = _con_viaje(api, db, refrigerado=True, peso=100, tipo_carga="refrigerada")
    r = compartir(api, v.id, peso=100, tipo_carga="general")
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "CARGA_NO_COMPATIBLE"
    assert compartir(api, v.id, peso=100, tipo_carga="refrigerada").status_code == 201
    w, _ = _con_viaje(api, db, refrigerado=False, peso=100)
    assert compartir(api, w.id, peso=100, tipo_carga="refrigerada").status_code == 409


def test_vehiculo_sin_viaje_no_acepta_carga_compartida(api, db):
    v = vehiculo(db, ubicacion=BOGOTA)
    r = compartir(api, v.id, peso=10)
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "VEHICULO_NO_ACEPTA_CARGA"


def test_vehiculo_inexistente(api):
    assert compartir(api, uuid.uuid4()).status_code == 404


def test_reintentar_el_mismo_envio_no_duplica_el_peso(api, db):
    v, _ = _con_viaje(api, db, peso=300)
    cuerpo = {"envio_id": str(uuid.uuid4()), "vehiculo_id": str(v.id), "peso_kg": 200}
    a, b = api.post("/reservas/compartida", json=cuerpo), api.post("/reservas/compartida", json=cuerpo)
    assert (a.status_code, b.status_code) == (201, 200) and b.json()["ya_existia"] is True
    assert api.get(f"/vehiculos/{v.id}/ocupacion").json()["peso_reservado_kg"] == 500


def test_liberar_una_carga_no_libera_el_vehiculo_hasta_la_ultima(api, db):
    v, base = _con_viaje(api, db, peso=300)
    extra = compartir(api, v.id, peso=200).json()
    r1 = api.post("/reservas/liberar", json={"envio_id": extra["envio_id"]}).json()
    assert r1["liberado"] and r1["vehiculo_libre"] is False and r1["cargas_restantes"] == 1
    db.expire_all()
    assert db.get(Vehiculo, v.id).estado == "en_transito" and float(db.get(Vehiculo, v.id).peso_reservado_kg) == 300
    r2 = api.post("/reservas/liberar", json={"envio_id": base["envio_id"]}).json()
    assert r2["vehiculo_libre"] is True and r2["cargas_restantes"] == 0
    db.expire_all()
    f = db.get(Vehiculo, v.id)
    assert f.estado == "active" and float(f.peso_reservado_kg) == 0
    assert api.post("/reservas/liberar", json={"envio_id": base["envio_id"]}).json()["liberado"] is False


def test_se_puede_liberar_primero_la_carga_original_y_el_vehiculo_sigue_ocupado(api, db):
    v, base = _con_viaje(api, db, peso=300)
    compartir(api, v.id, peso=200)
    r = api.post("/reservas/liberar", json={"envio_id": base["envio_id"]}).json()
    assert r["vehiculo_libre"] is False
    assert api.get(f"/vehiculos/{v.id}/ocupacion").json()["peso_reservado_kg"] == 200


def test_el_vehiculo_con_carga_compartida_no_se_ofrece_para_una_reserva_exclusiva(api, db):
    _con_viaje(api, db, peso=100)
    assert reservar(api, peso=10, punto=BOGOTA).status_code == 409


def test_conciliar_corrige_contadores_desviados(api, db):
    v, _ = _con_viaje(api, db, peso=300)
    compartir(api, v.id, peso=200)
    v.peso_reservado_kg = 999
    db.commit()
    r = api.post("/reservas/conciliar")
    assert r.status_code == 200, r.text
    assert api.get(f"/vehiculos/{v.id}/ocupacion").json()["peso_reservado_kg"] == 500


def test_ocupacion_lista_las_cargas_a_bordo(api, db):
    v, _ = _con_viaje(api, db, peso=300)
    compartir(api, v.id, peso=200)
    o = api.get(f"/vehiculos/{v.id}/ocupacion").json()
    assert len(o["cargas"]) == 2 and o["peso_disponible_kg"] == 500

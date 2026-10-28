"""Escenario C: se elige el vehículo elegible MÁS CERCANO al origen, con criterios deterministas y honestos."""
import uuid

from app.models import Vehiculo
from utiles import BOGOTA, BRASILIA, BUENOS_AIRES, CALI, GIRARDOT, MONTERIA, origen, reservar, vehiculo


def test_elige_el_mas_cercano_aunque_otro_tenga_menos_capacidad(api, db):
    lejos = vehiculo(db, capacidad=500, ubicacion=MONTERIA)
    cerca = vehiculo(db, capacidad=5000, ubicacion=GIRARDOT)
    r = reservar(api, peso=100, punto=BOGOTA)
    assert r.status_code == 201, r.text
    assert r.json()["vehiculo"]["id"] == str(cerca.id) and r.json()["vehiculo"]["id"] != str(lejos.id)
    assert r.json()["reposicion"]["distancia_linea_recta_km"] < 150
    assert r.json()["decision"]["criterio"] == "cercania_linea_recta"


def test_sin_origen_se_mantiene_el_criterio_anterior_de_menor_capacidad(api, db):
    vehiculo(db, capacidad=5000, ubicacion=BOGOTA)
    chico = vehiculo(db, capacidad=500, ubicacion=MONTERIA)
    r = reservar(api, peso=100)
    assert r.json()["vehiculo"]["id"] == str(chico.id)


def test_sin_ubicacion_conocida_es_ultimo_recurso_pero_sirve_si_es_el_unico(api, db):
    sin = vehiculo(db, capacidad=500)  # nunca se le inventa una posición
    con = vehiculo(db, capacidad=9000, ubicacion=MONTERIA)
    r = reservar(api, peso=100, punto=BOGOTA)
    assert r.json()["vehiculo"]["id"] == str(con.id)
    r2 = reservar(api, peso=100, punto=BOGOTA)
    assert r2.status_code == 201 and r2.json()["vehiculo"]["id"] == str(sin.id)
    assert r2.json()["reposicion"]["distancia_linea_recta_km"] is None
    assert r2.json()["decision"]["sin_ubicacion_fiable"] is True


def test_una_ubicacion_no_fiable_cuenta_como_desconocida(api, db):
    dudoso = vehiculo(db, capacidad=500, ubicacion=BOGOTA, fiable=False)
    firme = vehiculo(db, capacidad=500, ubicacion=CALI)
    r = reservar(api, peso=100, punto=BOGOTA)
    assert r.json()["vehiculo"]["id"] == str(firme.id) and r.json()["vehiculo"]["id"] != str(dudoso.id)


def test_vehiculos_en_otro_pais_se_descartan_por_defecto(api, db):
    vehiculo(db, ubicacion=BRASILIA)
    r = reservar(api, peso=100, punto=BOGOTA)
    assert r.status_code == 409
    assert r.json()["detail"]["causa"] == "FUERA_DE_ALCANCE"
    assert r.json()["detail"]["descartados"]["FRONTERA"] == 1


def test_el_cruce_de_frontera_se_habilita_por_variable_de_entorno(api, db, monkeypatch):
    monkeypatch.setenv("REPOSICION_INTERNACIONAL", "true")
    monkeypatch.setenv("MAX_REPOSICION_KM", "0")
    v = vehiculo(db, ubicacion=BUENOS_AIRES)
    r = reservar(api, peso=100, punto=BOGOTA)
    assert r.status_code == 201 and r.json()["vehiculo"]["id"] == str(v.id)


def test_el_tope_de_kilometros_descarta_los_demasiado_lejanos(api, db, monkeypatch):
    monkeypatch.setenv("MAX_REPOSICION_KM", "300")
    vehiculo(db, ubicacion=MONTERIA)  # ~ 600 km de Bogotá en línea recta
    r = reservar(api, peso=100, punto=BOGOTA)
    assert r.status_code == 409 and r.json()["detail"]["descartados"]["TOPE_DISTANCIA"] == 1


def test_empate_de_distancia_se_resuelve_siempre_igual(api, db):
    a = vehiculo(db, capacidad=800, ubicacion=CALI, placa="AAA111")
    vehiculo(db, capacidad=800, ubicacion=CALI, placa="BBB222")
    ids = []
    for _ in range(2):
        r = reservar(api, peso=100, punto=CALI)
        ids.append(r.json()["vehiculo"]["id"])
        api.post("/reservas/liberar", json={"envio_id": r.json()["envio_id"]})
        db.expire_all()
        for v in db.query(Vehiculo).all():  # tras liberar, vuelve a estar en Cali (fiable)
            v.ubicacion_confiable = True
        db.commit()
    assert ids[0] == ids[1] == str(a.id)


def test_no_se_elige_un_vehiculo_sin_peso_suficiente_aunque_este_al_lado(api, db):
    vehiculo(db, capacidad=100, ubicacion=BOGOTA)
    lejos = vehiculo(db, capacidad=5000, ubicacion=GIRARDOT)
    r = reservar(api, peso=2000, punto=BOGOTA)
    assert r.json()["vehiculo"]["id"] == str(lejos.id)


def test_vehiculo_excluido_no_se_vuelve_a_elegir(api, db):
    cerca = vehiculo(db, ubicacion=BOGOTA)
    otro = vehiculo(db, ubicacion=GIRARDOT)
    r = api.post("/reservas/", json={"envio_id": str(uuid.uuid4()), "peso_kg": 100, "origen": origen(BOGOTA),
                                      "excluir_vehiculos": [str(cerca.id)]})
    assert r.json()["vehiculo"]["id"] == str(otro.id)


def test_el_vehiculo_ocupado_no_participa_en_la_seleccion_exclusiva(api, db):
    cerca = vehiculo(db, ubicacion=BOGOTA)
    lejos = vehiculo(db, ubicacion=GIRARDOT)
    assert reservar(api, punto=BOGOTA).json()["vehiculo"]["id"] == str(cerca.id)
    assert reservar(api, punto=BOGOTA).json()["vehiculo"]["id"] == str(lejos.id)
    assert reservar(api, punto=BOGOTA).status_code == 409


def test_el_mismo_envio_reintentado_devuelve_el_mismo_vehiculo(api, db):
    vehiculo(db, ubicacion=BOGOTA)
    vehiculo(db, ubicacion=GIRARDOT)
    cuerpo = {"envio_id": str(uuid.uuid4()), "peso_kg": 100, "origen": origen(BOGOTA)}
    a = api.post("/reservas/", json=cuerpo)
    b = api.post("/reservas/", json=cuerpo)
    assert a.status_code == 201 and b.status_code == 200
    assert a.json()["vehiculo"]["id"] == b.json()["vehiculo"]["id"] and b.json()["ya_existia"] is True


def test_vehiculo_en_mantenimiento_o_sin_conductor_disponible_no_cuenta(api, db):
    vehiculo(db, ubicacion=BOGOTA, estado="en_mantenimiento")
    vehiculo(db, ubicacion=BOGOTA, conductor_estado="en_ruta")
    assert reservar(api, punto=BOGOTA).status_code == 409


def test_un_reintento_devuelve_la_misma_ubicacion_de_partida(api, db):
    vehiculo(db, ubicacion=GIRARDOT)
    cuerpo = {"envio_id": str(uuid.uuid4()), "peso_kg": 100, "origen": origen(BOGOTA)}
    a = api.post("/reservas/", json=cuerpo).json()
    b = api.post("/reservas/", json=cuerpo).json()
    assert a["reposicion"]["desde"]["latitud"] == 4.301
    assert b["reposicion"]["desde"] == a["reposicion"]["desde"]


def test_liberar_sin_movimiento_conserva_la_ubicacion_y_liberar_normal_no(api, db):
    v = vehiculo(db, ubicacion=GIRARDOT)
    r = reservar(api, punto=BOGOTA).json()
    api.post("/reservas/liberar", json={"envio_id": r["envio_id"], "sin_movimiento": True})
    db.expire_all()
    assert db.get(Vehiculo, v.id).ubicacion_confiable is True
    r2 = reservar(api, punto=BOGOTA).json()
    api.post("/reservas/liberar", json={"envio_id": r2["envio_id"]})
    db.expire_all()
    assert db.get(Vehiculo, v.id).ubicacion_confiable is False

import itertools
import uuid

from app.models import Conductor, Reserva, Vehiculo

_n = itertools.count(1)


def flota(db, capacidades, m3=None, refrigerado=False, hazmat=False, estado="active"):
    """Un vehículo con su conductor por cada capacidad."""
    for cap in capacidades:
        n = next(_n)
        v = Vehiculo(id=uuid.uuid4(), placa=f"AAA{n:03d}", tipo="camion", capacidad_kg=cap, capacidad_m3=m3,
                     estado=estado, capacidad_refrigeracion=refrigerado, certificado_hazmat=hazmat)
        db.add(v); db.flush()
        db.add(Conductor(id=uuid.uuid4(), codigo_conductor=n, nombre=f"C{n}", licencia_numero=f"L{n}",
                         categorias_licencia="C2", anios_experiencia=5, certificacion_hazmat=hazmat, vehiculo_id=v.id))
    db.commit()


def viab(api, **kw):
    r = api.post("/reservas/viabilidad", json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def test_cabe_en_un_vehiculo_no_requiere_division(api, db):
    flota(db, [1000, 500])
    d = viab(api, peso_kg=400)
    assert d["viable"] and not d["requiere_division"] and d["capacidad_maxima_kg"] == 1000
    assert d["compatibles"] == 2 and d["partes"] is None


def test_excede_y_es_indivisible_da_el_codigo_pedido(api, db):
    flota(db, [1000, 1000, 500])
    d = viab(api, peso_kg=1200)
    assert d["viable"] is False
    assert d["causa"] == "CARGA_INDIVISIBLE_EXCEDE_CAPACIDAD"
    assert d["requiere_division"] and d["division_posible"] and d["capacidad_maxima_kg"] == 1000
    assert "divisible" in d["mensaje"]


def test_excede_y_es_divisible_devuelve_el_plan_1000_mas_200(api, db):
    flota(db, [1000, 1000, 500])
    d = viab(api, peso_kg=1200, es_divisible=True)
    assert d["viable"] and d["requiere_division"]
    assert [p["peso_kg"] for p in d["partes"]] == [1000, 200]
    assert [p["capacidad_vehiculo_kg"] for p in d["partes"]] == [1000, 500]
    assert d["desperdicio_kg"] == 300


def test_dos_toneladas_en_dos_de_mil(api, db):
    flota(db, [1000, 1000, 500])
    d = viab(api, peso_kg=2000, es_divisible=True)
    assert [p["peso_kg"] for p in d["partes"]] == [1000, 1000]


def test_divisible_pero_la_flota_no_alcanza(api, db):
    flota(db, [1000, 1000, 500])
    d = viab(api, peso_kg=3000, es_divisible=True)
    assert d["viable"] is False and d["causa"] == "CAPACIDAD_EXCEDIDA" and d["division_posible"] is False
    assert "2500" in d["mensaje"]


def test_indivisible_que_ni_dividida_cabe_marca_division_imposible(api, db):
    flota(db, [1000, 500])
    d = viab(api, peso_kg=5000)
    assert d["causa"] == "CARGA_INDIVISIBLE_EXCEDE_CAPACIDAD" and d["division_posible"] is False


def test_la_capacidad_maxima_solo_cuenta_vehiculos_compatibles_con_el_tipo_de_carga(api, db):
    flota(db, [5000])                       # grande pero sin refrigeración
    flota(db, [800], refrigerado=True)
    d = viab(api, peso_kg=1000, tipo_carga="refrigerada")
    assert d["capacidad_maxima_kg"] == 800 and d["causa"] == "CARGA_INDIVISIBLE_EXCEDE_CAPACIDAD"


def test_sin_vehiculo_refrigerado_o_hazmat_mantiene_su_causa(api, db):
    flota(db, [1000])
    assert viab(api, peso_kg=100, tipo_carga="refrigerada")["causa"] == "SIN_REFRIGERACION"
    assert viab(api, peso_kg=100, es_hazmat=True)["causa"] == "SIN_HABILITACION_HAZMAT"


def test_sin_flota_operativa(api, db):
    flota(db, [1000], estado="fuera_de_servicio")
    assert viab(api, peso_kg=100)["causa"] == "SIN_FLOTA_OPERATIVA"


def test_volumen_es_secundario_sin_dato_en_el_vehiculo_no_bloquea(api, db):
    flota(db, [1000], m3=None)
    assert viab(api, peso_kg=900, volumen_m3=999)["viable"] is True


def test_volumen_declarado_y_vehiculo_con_m3_se_respeta(api, db):
    flota(db, [1000], m3=10)
    d = viab(api, peso_kg=900, volumen_m3=12)
    assert d["viable"] is False and d["causa"] == "VOLUMEN_EXCEDIDO"


def test_volumen_excedido_pero_divisible_se_reparte_en_proporcion_y_cada_parte_cabe(api, db):
    flota(db, [1000, 1000], m3=10)
    d = viab(api, peso_kg=900, volumen_m3=12, es_divisible=True)
    assert d["viable"] and len(d["partes"]) == 2
    assert round(sum(p["volumen_m3"] for p in d["partes"]), 2) == 12
    assert all(p["volumen_m3"] <= 10 for p in d["partes"])


def test_vehiculos_ocupados_cuentan_como_compatibles_pero_no_como_disponibles(api, db):
    flota(db, [1000]); flota(db, [1000], estado="en_transito")
    d = viab(api, peso_kg=500)
    assert d["compatibles"] == 2 and d["disponibles_ahora"] == 1


def test_plan_division_evalua_como_divisible_sin_pedirlo(api, db):
    flota(db, [1000, 1000, 500])
    r = api.post("/reservas/plan-division", json={"peso_kg": 1200})
    assert r.status_code == 200 and [p["peso_kg"] for p in r.json()["partes"]] == [1000, 200]


def test_viabilidad_no_reserva_nada(api, db):
    flota(db, [1000])
    viab(api, peso_kg=500)
    assert db.query(Reserva).count() == 0 and db.query(Vehiculo).first().estado == "active"


# ---------- guarda del cambio manual de estado ----------

def _vehiculo(db):
    return db.query(Vehiculo).first()


def test_no_se_puede_poner_en_transito_a_mano(api, db):
    flota(db, [1000])
    r = api.patch(f"/vehiculos/{_vehiculo(db).id}/estado", json={"estado": "en_transito"})
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "ESTADO_GESTIONADO_POR_RESERVAS"


def test_estados_normales_siguen_funcionando(api, db):
    flota(db, [1000])
    vid = _vehiculo(db).id
    for estado in ("en_mantenimiento", "fuera_de_servicio", "active"):
        r = api.patch(f"/vehiculos/{vid}/estado", json={"estado": estado})
        assert r.status_code == 200 and r.json()["estado"] == estado
    assert api.patch(f"/vehiculos/{vid}/estado", json={"estado": "inventado"}).status_code == 422


def test_con_reserva_activa_no_se_vuelve_a_ofrecer_el_vehiculo(api, db):
    flota(db, [1000])
    v = _vehiculo(db)
    c = db.query(Conductor).first()
    v.estado = "en_mantenimiento"
    db.add(Reserva(envio_id=uuid.uuid4(), vehiculo_id=v.id, conductor_id=c.id, estado="reservada")); db.commit()
    r = api.patch(f"/vehiculos/{v.id}/estado", json={"estado": "active"})
    assert r.status_code == 200 and r.json()["estado"] == "en_transito"

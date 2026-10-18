from decimal import Decimal as D

import pytest

from app.division import planificar, seleccionar_vehiculos


def pesos(plan):
    return [float(p["peso_kg"]) for p in plan["partes"]]


def test_ejemplo_del_usuario_1200_kg_es_1000_mas_200_en_el_vehiculo_de_500():
    plan = planificar(1200, [1000, 1000, 500])
    assert pesos(plan) == [1000, 200]
    assert [float(p["capacidad_vehiculo_kg"]) for p in plan["partes"]] == [1000, 500]
    assert plan["desperdicio_kg"] == D("300.00")


def test_2000_kg_con_dos_vehiculos_de_1000():
    assert pesos(planificar(2000, [1000, 1000, 500])) == [1000, 1000]


def test_primero_el_menor_numero_de_vehiculos_aunque_desperdicie_mas():
    # 1500 cabe en 2 de (1000, 600, 600, 500)? el mínimo es 2 vehículos; se elige 1000+500 (desperdicio 0)
    plan = planificar(1500, [1000, 600, 600, 500])
    assert pesos(plan) == [1000, 500]
    # 1800 necesita 3 (1000+600+600=2200) pues 1000+600=1600 < 1800
    assert len(planificar(1800, [1000, 600, 600, 500])["partes"]) == 3


def test_entre_igual_numero_de_vehiculos_gana_el_de_menor_desperdicio():
    plan = planificar(1100, [1000, 900, 300, 250])
    assert len(plan["partes"]) == 2
    assert plan["desperdicio_kg"] == D("50.00")   # 900 + 250 = 1150; las demás parejas desperdician más


def test_no_alcanza_la_flota():
    assert planificar(3000, [1000, 1000, 500]) is None
    assert seleccionar_vehiculos(2500.01, [1000, 1000, 500]) is None


def test_suma_exacta_de_la_flota_usa_todos_los_vehiculos():
    plan = planificar(2500, [1000, 1000, 500])
    assert pesos(plan) == [1000, 1000, 500] and plan["desperdicio_kg"] == D("0.00")


@pytest.mark.parametrize("peso,caps", [(1200, [1000, 1000, 500]), (4321.55, [1500, 1200.5, 900, 800, 700, 3000]), (999.99, [500, 500, 500])])
def test_las_partes_suman_el_peso_y_ninguna_pasa_la_capacidad(peso, caps):
    plan = planificar(peso, caps)
    assert sum(p["peso_kg"] for p in plan["partes"]) == D(str(peso)).quantize(D("0.01"))
    assert all(0 < p["peso_kg"] <= p["capacidad_vehiculo_kg"] for p in plan["partes"])


def test_el_volumen_se_divide_en_proporcion_al_peso_y_suma_el_total():
    plan = planificar(1200, [1000, 1000, 500], volumen=12)
    vols = [p["volumen_m3"] for p in plan["partes"]]
    assert vols == [D("10.00"), D("2.00")] and sum(vols) == D("12.00")
    plan = planificar(1000, [400, 400, 400], volumen=10)
    assert sum(p["volumen_m3"] for p in plan["partes"]) == D("10.00")


def test_sin_volumen_las_partes_no_llevan_volumen():
    assert all(p["volumen_m3"] is None for p in planificar(1200, [1000, 1000, 500])["partes"])


def test_coincide_con_la_busqueda_exhaustiva_en_flotas_aleatorias():
    import itertools
    import random

    azar = random.Random(7)
    for _ in range(300):
        caps = [azar.choice([200, 300, 500, 600, 800, 1000, 1500, 2000]) for _ in range(azar.randint(1, 8))]
        peso = azar.randint(100, sum(caps) + 500)
        plan = planificar(peso, caps)
        if sum(caps) < peso:
            assert plan is None
            continue
        mejor = None
        for k in range(1, len(caps) + 1):
            sumas = [sum(c) for c in itertools.combinations(caps, k) if sum(c) >= peso]
            if sumas:
                mejor = (k, min(sumas) - peso)
                break
        assert (len(plan["partes"]), float(plan["desperdicio_kg"])) == mejor, (peso, caps)

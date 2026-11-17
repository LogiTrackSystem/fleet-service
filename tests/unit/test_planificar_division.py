"""Unitaria 1: division.planificar reparte un pedido pesado entre los vehículos necesarios."""
from decimal import Decimal

from app.division import planificar


def test_planificar_1200_kg_son_1000_mas_200_y_none_si_no_alcanza():
    plan = planificar(1200, [1000, 1000, 500])
    assert [float(p["peso_kg"]) for p in plan["partes"]] == [1000, 200]
    assert plan["desperdicio_kg"] == Decimal("300.00")
    assert planificar(5000, [1000, 1000, 500]) is None

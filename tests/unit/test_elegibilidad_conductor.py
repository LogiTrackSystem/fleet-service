"""Unitaria 2: elegibilidad.errores_de_elegibilidad valida licencia, experiencia y HAZMAT del conductor."""
from types import SimpleNamespace

from app.elegibilidad import errores_de_elegibilidad

CAMION = SimpleNamespace(tipo="camion", placa="ABC123", certificado_hazmat=False)


def test_conductor_elegible_para_camion_y_rechazado_sin_licencia_ni_experiencia():
    assert errores_de_elegibilidad(CAMION, "C2", 5, False) == []
    errores = errores_de_elegibilidad(CAMION, "B1", 0, False)
    assert len(errores) == 2  # licencia insuficiente y poca experiencia

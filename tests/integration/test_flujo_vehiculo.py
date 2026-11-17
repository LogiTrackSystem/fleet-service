"""Integración: alta de un vehículo por API, consulta por placa y cambio de estado."""
import uuid


def test_vehiculo_se_crea_se_consulta_y_cambia_de_estado(api):
    cuerpo = {
        "placa": "KQA794", "tipo": "camion", "capacidad_kg": 5000, "anio": 2022,
        "ubicacion_id": str(uuid.uuid4()), "ubicacion_nombre": "Bogotá",
        "latitud": 4.7110, "longitud": -74.0721, "codigo_pais": "CO",
    }
    creado = api.post("/vehiculos/", json=cuerpo)
    leido = api.get("/vehiculos/placa/KQA794")
    cambio = api.patch(f"/vehiculos/{creado.json()['id']}/estado", json={"estado": "en_mantenimiento"})
    assert creado.status_code == 201 and float(leido.json()["capacidad_kg"]) == 5000
    assert cambio.status_code == 200 and cambio.json()["estado"] == "en_mantenimiento"

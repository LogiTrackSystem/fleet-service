"""Ayudas comunes de las pruebas de ubicación, cercanía y carga compartida."""
import itertools
import uuid
from datetime import datetime, timezone

from app.models import Conductor, Vehiculo

_n = itertools.count(100)

# Coordenadas reales aproximadas de ciudades del catálogo de Routing
MONTERIA = (8.7480, -75.8814, "CO")
CALI = (3.4516, -76.5320, "CO")
BOGOTA = (4.7110, -74.0721, "CO")
GIRARDOT = (4.3010, -74.8039, "CO")
BRASILIA = (-15.7939, -47.8828, "BR")
BUENOS_AIRES = (-34.6037, -58.3816, "AR")


def vehiculo(db, capacidad=1000, m3=None, ubicacion=None, fiable=True, estado="active", refrigerado=False,
             hazmat=False, placa=None, conductor_estado="available"):
    n = next(_n)
    v = Vehiculo(id=uuid.uuid4(), placa=placa or f"TST{n:03d}", tipo="camion", capacidad_kg=capacidad, capacidad_m3=m3,
                 estado=estado, capacidad_refrigeracion=refrigerado, certificado_hazmat=hazmat)
    if ubicacion is not None:
        v.latitud, v.longitud, v.codigo_pais = ubicacion
        v.ubicacion_actualizada_en = datetime.now(timezone.utc)
        v.ubicacion_fuente = "registro_gestor"
        v.ubicacion_confiable = fiable
    db.add(v)
    db.flush()
    db.add(Conductor(id=uuid.uuid4(), codigo_conductor=n, nombre=f"Conductor {n}", licencia_numero=f"LIC{n}",
                     categorias_licencia="C2", anios_experiencia=8, certificacion_hazmat=hazmat,
                     vehiculo_id=v.id, estado=conductor_estado))
    db.commit()
    return v


def origen(punto):
    return {"latitud": punto[0], "longitud": punto[1], "codigo_pais": punto[2]}


def reservar(api, peso=100, punto=None, **extra):
    cuerpo = {"envio_id": str(uuid.uuid4()), "peso_kg": peso, **extra}
    if punto is not None:
        cuerpo["origen"] = origen(punto)
    return api.post("/reservas/", json=cuerpo)


def compartir(api, vehiculo_id, peso=100, **extra):
    cuerpo = {"envio_id": str(uuid.uuid4()), "vehiculo_id": str(vehiculo_id), "peso_kg": peso, **extra}
    return api.post("/reservas/compartida", json=cuerpo)

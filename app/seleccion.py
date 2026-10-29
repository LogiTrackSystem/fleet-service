"""Reglas puras de asignación (sin base de datos): cercanía al origen y carga compartida.

- Cercanía: se ordena por distancia en LÍNEA RECTA entre la última ubicación real del vehículo y el origen del
  envío. Es una aproximación: no equivale a la distancia por carretera. Un vehículo sin ubicación fiable no tiene
  distancia y se ordena después de los que sí la tienen (nunca se inventa una posición).
- Alcance: tope MAX_REPOSICION_KM (0 = sin tope) y, por defecto, no se cruzan fronteras en vacío
  (REPOSICION_INTERNACIONAL=true lo permite).
- Carga compartida: HAZMAT nunca comparte vehículo; la carga refrigerada solo comparte con refrigerada; el peso y el
  volumen a bordo más los de la carga nueva no pueden superar la capacidad.
"""
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .geo import haversine_km

DEFECTO_MAX_REPOSICION_KM = 1500.0


def max_reposicion_km() -> float:
    try:
        return max(0.0, float(os.getenv("MAX_REPOSICION_KM", str(DEFECTO_MAX_REPOSICION_KM))))
    except ValueError:
        return DEFECTO_MAX_REPOSICION_KM


def reposicion_internacional() -> bool:
    return os.getenv("REPOSICION_INTERNACIONAL", "false").strip().lower() in ("1", "true", "si", "sí", "yes")


@dataclass(frozen=True)
class Origen:
    latitud: float
    longitud: float
    codigo_pais: Optional[str] = None


def ubicacion_fiable(vehiculo) -> bool:
    return bool(vehiculo.ubicacion_confiable) and vehiculo.latitud is not None and vehiculo.longitud is not None


def distancia_al_origen(vehiculo, origen: Origen) -> Optional[float]:
    if not ubicacion_fiable(vehiculo):
        return None
    return haversine_km(vehiculo.latitud, vehiculo.longitud, origen.latitud, origen.longitud)


def fuera_de_alcance(vehiculo, origen: Origen, distancia: Optional[float]) -> Optional[str]:
    """Motivo por el que el vehículo no puede reposicionarse hasta el origen, o None si puede."""
    if distancia is None:
        return None  # sin ubicación fiable no se puede juzgar: queda como último recurso
    if (not reposicion_internacional() and origen.codigo_pais and vehiculo.codigo_pais
            and vehiculo.codigo_pais.upper() != origen.codigo_pais.upper()):
        return "FRONTERA"
    tope = max_reposicion_km()
    if tope and distancia > tope:
        return "TOPE_DISTANCIA"
    return None


def _clave(vehiculo, distancia):
    return (
        distancia is None,
        round(distancia, 3) if distancia is not None else 0.0,
        float(vehiculo.capacidad_kg),
        vehiculo.placa,
        str(vehiculo.id),
    )


def ordenar_candidatos(parejas, origen: Optional[Origen]):
    """parejas: [(vehiculo, conductor)]. Devuelve (ordenadas, descartadas) donde ordenadas = [(v, c, distancia_km|None)]
    y descartadas = {motivo: cantidad}. Sin origen se conserva el criterio anterior (menor capacidad suficiente, placa)."""
    ordenadas, descartadas = [], {}
    for v, c in parejas:
        d = distancia_al_origen(v, origen) if origen is not None else None
        if origen is not None:
            motivo = fuera_de_alcance(v, origen, d)
            if motivo:
                descartadas[motivo] = descartadas.get(motivo, 0) + 1
                continue
        ordenadas.append((v, c, d))
    if origen is None:
        ordenadas.sort(key=lambda t: (float(t[0].capacidad_kg), t[0].placa, str(t[0].id)))
    else:
        ordenadas.sort(key=lambda t: _clave(t[0], t[2]))
    return ordenadas, descartadas


# ---------- Carga compartida ----------

def verificar_compartida(vehiculo, conductor, activas, peso, volumen, tipo_carga, es_hazmat) -> Optional[tuple]:
    """Devuelve (codigo, mensaje) si la carga NO puede subir al vehículo, o None si cabe y es compatible.
    `activas`: reservas vigentes del vehículo (con tipo_carga, es_hazmat)."""
    if vehiculo.estado != "en_transito" or not activas:
        return ("VEHICULO_NO_ACEPTA_CARGA", "El vehículo no tiene un viaje en curso al que sumar carga")
    if conductor is None or conductor.estado != "en_ruta":
        return ("VEHICULO_NO_ACEPTA_CARGA", "El conductor del vehículo no está en ruta")
    if es_hazmat or any(a.es_hazmat for a in activas):
        return ("HAZMAT_NO_COMPARTE", "La carga HAZMAT no comparte vehículo con otra carga")
    if tipo_carga == "refrigerada" and not vehiculo.capacidad_refrigeracion:
        return ("SIN_REFRIGERACION", "El vehículo no tiene refrigeración")
    if any((a.tipo_carga or "general") != tipo_carga for a in activas):
        return ("CARGA_NO_COMPATIBLE", "La carga refrigerada y la general no se mezclan en un mismo vehículo")
    if Decimal(str(vehiculo.peso_reservado_kg)) + Decimal(str(peso)) > Decimal(str(vehiculo.capacidad_kg)):
        return ("CAPACIDAD_EXCEDIDA", "El peso a bordo más la carga nueva supera la capacidad del vehículo")
    if volumen is not None and vehiculo.capacidad_m3 is not None:
        if Decimal(str(vehiculo.volumen_reservado_m3)) + Decimal(str(volumen)) > Decimal(str(vehiculo.capacidad_m3)):
            return ("VOLUMEN_EXCEDIDO", "El volumen a bordo más la carga nueva supera la capacidad del vehículo")
    return None

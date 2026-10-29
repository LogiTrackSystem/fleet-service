"""Reparto de una carga que no cabe en un solo vehículo (función pura, sin base de datos).

Criterio acordado: primero el MENOR número de vehículos y, entre las opciones con ese número,
la que desperdicia menos capacidad. Cada vehículo se usa una sola vez (una reserva activa por vehículo).

Ejemplo: 1200 kg con vehículos de 1000, 1000 y 500 kg  ->  partes de 1000 y 200 kg
(se elige el par 1000+500, que desperdicia 300 kg, y no 1000+1000, que desperdicia 800 kg).
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

CENTESIMA = Decimal("0.01")
LIMITE_NODOS = 200_000  # tope de seguridad de la búsqueda; con flotas normales no se alcanza


def _a_centi(valor) -> int:
    return int((Decimal(str(valor)) / CENTESIMA).to_integral_value(rounding=ROUND_HALF_UP))


def _de_centi(valor: int) -> Decimal:
    return (Decimal(valor) * CENTESIMA).quantize(CENTESIMA)


def seleccionar_vehiculos(peso, capacidades) -> Optional[list]:
    """Devuelve las capacidades (de mayor a menor) de los vehículos elegidos, o None si la suma
    de todas no alcanza para el peso."""
    objetivo = _a_centi(peso)
    caps = sorted((_a_centi(c) for c in capacidades if c is not None and _a_centi(c) > 0), reverse=True)
    if sum(caps) < objetivo:
        return None

    # k = menor cantidad de vehículos cuya suma (tomando los más grandes) alcanza
    acumulado, k = 0, 0
    for c in caps:
        acumulado += c
        k += 1
        if acumulado >= objetivo:
            break

    n = len(caps)
    # suma de los r elementos más pequeños desde la posición i (r <= n - i): son los últimos r
    sufijo = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        sufijo[i] = sufijo[i + 1] + caps[i]
    prefijo_grande = [0] * (n + 1)
    for i in range(n):
        prefijo_grande[i + 1] = prefijo_grande[i] + caps[i]

    mejor = {"suma": sum(caps[:k]), "elegidos": list(range(k))}
    nodos = [0]

    def buscar(i, faltan, suma, elegidos):
        nodos[0] += 1
        if nodos[0] > LIMITE_NODOS:
            return
        if faltan == 0:
            if objetivo <= suma < mejor["suma"]:
                mejor["suma"], mejor["elegidos"] = suma, list(elegidos)
            return
        if n - i < faltan:
            return
        # cota superior: aun tomando los más grandes que quedan, ¿se alcanza el peso?
        if suma + (prefijo_grande[i + faltan] - prefijo_grande[i]) < objetivo:
            return
        # cota inferior: aun tomando los más pequeños que quedan, ¿se supera lo mejor encontrado?
        if suma + (sufijo[n - faltan] if faltan else 0) >= mejor["suma"]:
            return
        for j in range(i, n - faltan + 1):
            elegidos.append(j)
            buscar(j + 1, faltan - 1, suma + caps[j], elegidos)
            elegidos.pop()

    buscar(0, k, 0, [])
    return [_de_centi(caps[j]) for j in mejor["elegidos"]]


def repartir_peso(peso, capacidades_elegidas) -> list:
    """Llena primero los vehículos más grandes. Todas las partes quedan > 0 porque la selección
    usa el mínimo de vehículos."""
    restante = _a_centi(peso)
    partes = []
    for cap in sorted((_a_centi(c) for c in capacidades_elegidas), reverse=True):
        toma = min(cap, restante)
        if toma > 0:
            partes.append(_de_centi(toma))
        restante -= toma
    return partes


def repartir_volumen(volumen, peso, partes_kg) -> list:
    """Divide el volumen en proporción al peso de cada parte (la última absorbe el redondeo)."""
    if volumen is None:
        return [None] * len(partes_kg)
    volumen, peso = Decimal(str(volumen)), Decimal(str(peso))
    resultado, asignado = [], Decimal("0")
    for i, p in enumerate(partes_kg):
        if i == len(partes_kg) - 1:
            v = volumen - asignado
        else:
            v = (volumen * p / peso).quantize(CENTESIMA, rounding=ROUND_HALF_UP)
        v = max(v, CENTESIMA)
        resultado.append(v.quantize(CENTESIMA))
        asignado += v
    return resultado


def planificar(peso, capacidades, volumen=None) -> Optional[dict]:
    """Plan completo: lista de partes con su peso, su volumen proporcional y la capacidad del
    vehículo previsto. None si la flota compatible no alcanza para el peso."""
    elegidos = seleccionar_vehiculos(peso, capacidades)
    if elegidos is None:
        return None
    partes_kg = repartir_peso(peso, elegidos)
    volumenes = repartir_volumen(volumen, peso, partes_kg)
    capacidades_ordenadas = sorted(elegidos, reverse=True)
    partes = [
        {
            "parte": i + 1,
            "peso_kg": p,
            "volumen_m3": volumenes[i],
            "capacidad_vehiculo_kg": capacidades_ordenadas[i],
        }
        for i, p in enumerate(partes_kg)
    ]
    desperdicio = sum(capacidades_ordenadas) - sum(partes_kg)
    return {"partes": partes, "desperdicio_kg": Decimal(desperdicio).quantize(CENTESIMA)}

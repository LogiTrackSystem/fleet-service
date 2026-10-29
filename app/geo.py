import math

RADIO_TIERRA_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Distancia en LÍNEA RECTA sobre la superficie terrestre. No es distancia por carretera."""
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp = p2 - p1
    dl = math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * RADIO_TIERRA_KM * math.asin(math.sqrt(a))

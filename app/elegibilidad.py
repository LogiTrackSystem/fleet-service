REGLAS_POR_TIPO = {
    "furgoneta":    {"categorias": {"B1", "C1", "B2", "C2", "B3", "C3"}, "anios_minimos": 1},
    "camion":       {"categorias": {"B2", "C2", "B3", "C3"}, "anios_minimos": 2},
    "tractocamion": {"categorias": {"B3", "C3"}, "anios_minimos": 3},
}

HAZMAT_ANIOS_MINIMOS = 3


def errores_de_elegibilidad(vehiculo, categorias_licencia, anios_experiencia, certificacion_hazmat):
    """Devuelve una lista de motivos por los que el conductor NO puede ser el
    conductor fijo de este vehículo. Lista vacía = es elegible."""
    regla = REGLAS_POR_TIPO.get(vehiculo.tipo)
    if regla is None:
        return [
            f"El vehículo {vehiculo.placa} tiene el tipo '{vehiculo.tipo}', que no es válido. "
            "Reclasifícalo primero como furgoneta, camion o tractocamion."
        ]

    errores = []
    anios = anios_experiencia or 0
    categorias = {c.strip().upper() for c in (categorias_licencia or "").split(",") if c.strip()}

    if not categorias & regla["categorias"]:
        errores.append(
            f"Un {vehiculo.tipo} requiere licencia {', '.join(sorted(regla['categorias']))}; "
            f"el conductor tiene: {', '.join(sorted(categorias)) or 'ninguna'}"
        )
    if anios < regla["anios_minimos"]:
        errores.append(
            f"Un {vehiculo.tipo} requiere al menos {regla['anios_minimos']} año(s) de experiencia; "
            f"el conductor tiene {anios}"
        )
    if vehiculo.certificado_hazmat:
        if not certificacion_hazmat:
            errores.append("El vehículo está certificado para HAZMAT y el conductor no tiene certificación HAZMAT")
        if anios < HAZMAT_ANIOS_MINIMOS:
            errores.append(f"Un vehículo HAZMAT requiere al menos {HAZMAT_ANIOS_MINIMOS} años de experiencia; el conductor tiene {anios}")
    return errores
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..database import get_db
from ..division import planificar
from ..elegibilidad import HAZMAT_ANIOS_MINIMOS
from ..models import Conductor, Reserva, Vehiculo
from ..schemas import ReservaCompartidaSolicitud, ReservaSolicitud, LiberarSolicitud, ViabilidadSolicitud
from .. import seleccion


router = APIRouter(prefix="/reservas", tags=["reservas"])
ESTADOS_VEHICULO_OPERATIVOS = ("active", "en_transito", "en_mantenimiento")  # vuelven a estar disponibles
ESTADOS_CONDUCTOR_OPERATIVOS = ("available", "en_ruta")


def _requisitos(peso_kg, volumen_m3, tipo_carga, es_hazmat):
    """Condiciones que debe cumplir una pareja vehículo+conductor, en el orden en que se diagnostican."""
    requisitos = [("CAPACIDAD_EXCEDIDA", [Vehiculo.capacidad_kg >= peso_kg])]
    if volumen_m3 is not None:
        requisitos.append(
            ("VOLUMEN_EXCEDIDO", [or_(Vehiculo.capacidad_m3.is_(None), Vehiculo.capacidad_m3 >= volumen_m3)])
        )
    if tipo_carga == "refrigerada":
        requisitos.append(("SIN_REFRIGERACION", [Vehiculo.capacidad_refrigeracion.is_(True)]))
    if es_hazmat:
        requisitos.append((
            "SIN_HABILITACION_HAZMAT",
            [
                Vehiculo.certificado_hazmat.is_(True),
                Conductor.certificacion_hazmat.is_(True),
                Conductor.anios_experiencia >= HAZMAT_ANIOS_MINIMOS,
            ],
        ))
    return requisitos


def _parejas(db, estados_vehiculo, estados_conductor):
    return (
        db.query(Vehiculo, Conductor)
        .join(Conductor, Conductor.vehiculo_id == Vehiculo.id)
        .filter(Vehiculo.estado.in_(estados_vehiculo), Conductor.estado.in_(estados_conductor))
    )


def _compatibles(db, requisitos, estados_vehiculo, estados_conductor):
    consulta = _parejas(db, estados_vehiculo, estados_conductor)
    for _, condiciones in requisitos:
        consulta = consulta.filter(*condiciones)
    return consulta


def _mensaje_viabilidad(codigo, payload, maximo_kg):
    if codigo == "CAPACIDAD_EXCEDIDA":
        return (
            f"Ningún vehículo con conductor puede transportar {float(payload.peso_kg):g} kg "
            f"(la mayor capacidad de la flota es {float(maximo_kg or 0):g} kg)"
        )
    if codigo == "CARGA_INDIVISIBLE_EXCEDE_CAPACIDAD":
        return (
            f"La carga de {float(payload.peso_kg):g} kg no cabe en un solo vehículo "
            f"(la mayor capacidad compatible es {float(maximo_kg or 0):g} kg) y está marcada como indivisible. "
            "Si puede dividirse, márquela como divisible."
        )
    if codigo == "VOLUMEN_EXCEDIDO":
        return f"Ningún vehículo con conductor soporta {float(payload.volumen_m3):g} m³ junto con ese peso"
    if codigo == "SIN_REFRIGERACION":
        return "Ningún vehículo con refrigeración y conductor puede transportar esta carga"
    return (
        "Ningún vehículo certificado HAZMAT tiene un conductor con certificación HAZMAT "
        f"y al menos {HAZMAT_ANIOS_MINIMOS} años de experiencia"
    )


CONDICIONES_DE_PESO_Y_VOLUMEN = ("CAPACIDAD_EXCEDIDA", "VOLUMEN_EXCEDIDO")


def _respuesta(viable, causa=None, mensaje=None, compatibles=0, disponibles=0, maximo=None,
               requiere_division=False, division_posible=False, plan=None):
    return {
        "viable": viable,
        "causa": causa,
        "mensaje": mensaje,
        "compatibles": compatibles,
        "disponibles_ahora": disponibles,
        "capacidad_maxima_kg": float(maximo) if maximo is not None else None,
        "requiere_division": requiere_division,
        "division_posible": division_posible,
        "partes": (
            [
                {
                    "parte": p["parte"],
                    "peso_kg": float(p["peso_kg"]),
                    "volumen_m3": float(p["volumen_m3"]) if p["volumen_m3"] is not None else None,
                    "capacidad_vehiculo_kg": float(p["capacidad_vehiculo_kg"]),
                }
                for p in plan["partes"]
            ]
            if plan
            else None
        ),
        "desperdicio_kg": float(plan["desperdicio_kg"]) if plan else None,
    }


def _capacidad_efectiva(vehiculo, payload):
    """Kilos que el vehículo puede llevar de esta carga: su capacidad en kg y, solo si la carga declara
    volumen y el vehículo tiene capacidad_m3, lo que cabe por volumen (en proporción al peso)."""
    cap = Decimal(str(vehiculo.capacidad_kg))
    if payload.volumen_m3 is not None and vehiculo.capacidad_m3 is not None:
        por_volumen = Decimal(str(vehiculo.capacidad_m3)) * Decimal(str(payload.peso_kg)) / Decimal(str(payload.volumen_m3))
        cap = min(cap, por_volumen)
    return cap


def _evaluar_viabilidad(db, payload):
    """El peso manda: se busca primero un vehículo que lleve toda la carga. Si ninguno puede, la carga
    solo es viable cuando es divisible y la flota compatible alcanza (se devuelve el plan de partes).
    El volumen es un criterio secundario: solo cuenta si la carga lo declara y el vehículo tiene capacidad_m3."""
    base = _parejas(db, ESTADOS_VEHICULO_OPERATIVOS, ESTADOS_CONDUCTOR_OPERATIVOS)
    if base.count() == 0:
        return _respuesta(False, "SIN_FLOTA_OPERATIVA", "No hay vehículos operativos con conductor asignado en la flota")

    # 1) Requisitos que no dependen del peso (refrigeración, HAZMAT)
    consulta = base
    for codigo, condiciones in _requisitos(payload.peso_kg, payload.volumen_m3, payload.tipo_carga, payload.es_hazmat):
        if codigo in CONDICIONES_DE_PESO_Y_VOLUMEN:
            continue
        consulta = consulta.filter(*condiciones)
        if consulta.count() == 0:
            return _respuesta(False, codigo, _mensaje_viabilidad(codigo, payload, None))
    pool = consulta.all()
    maximo = max(Decimal(str(v.capacidad_kg)) for v, _ in pool)
    libres = sum(1 for v, c in pool if v.estado == "active" and c.estado == "available")

    # 2) ¿Hay un solo vehículo que lleve toda la carga (peso y, si aplica, volumen)?
    unico = consulta.filter(Vehiculo.capacidad_kg >= payload.peso_kg)
    if payload.volumen_m3 is not None:
        unico = unico.filter(or_(Vehiculo.capacidad_m3.is_(None), Vehiculo.capacidad_m3 >= payload.volumen_m3))
    if unico.count() > 0:
        libres_unico = unico.filter(Vehiculo.estado == "active", Conductor.estado == "available").count()
        return _respuesta(True, compatibles=unico.count(), disponibles=libres_unico, maximo=maximo)

    # 3) Ninguno la lleva completa: hay que dividirla (o rechazarla)
    por_peso = Decimal(str(payload.peso_kg)) > maximo
    causa_unica = "CAPACIDAD_EXCEDIDA" if por_peso else "VOLUMEN_EXCEDIDO"
    plan = planificar(payload.peso_kg, [_capacidad_efectiva(v, payload) for v, _ in pool], payload.volumen_m3)

    if not payload.es_divisible:
        causa = "CARGA_INDIVISIBLE_EXCEDE_CAPACIDAD" if por_peso else "VOLUMEN_EXCEDIDO"
        return _respuesta(
            False, causa, _mensaje_viabilidad(causa, payload, maximo), maximo=maximo,
            requiere_division=True, division_posible=plan is not None,
        )
    if plan is None:
        if por_peso:
            total = sum(Decimal(str(v.capacidad_kg)) for v, _ in pool)
            mensaje = (
                f"Aun dividiéndola, la flota compatible no alcanza: {float(payload.peso_kg):g} kg solicitados "
                f"y {float(total):g} kg de capacidad entre todos los vehículos"
            )
        else:
            mensaje = _mensaje_viabilidad("VOLUMEN_EXCEDIDO", payload, maximo)
        return _respuesta(False, causa_unica, mensaje, maximo=maximo, requiere_division=True)
    return _respuesta(
        True, compatibles=len(pool), disponibles=libres, maximo=maximo,
        requiere_division=True, division_posible=True, plan=plan,
    )


@router.post("/viabilidad")
def viabilidad(payload: ViabilidadSolicitud, db: Session = Depends(get_db)):
    """¿Existe en la flota alguna pareja vehículo+conductor (o varias, si la carga es divisible) capaz de
    transportar esta carga? No reserva nada.
    - 'capacidad_maxima_kg': el mayor peso que lleva un solo vehículo compatible.
    - 'requiere_division': ningún vehículo la lleva completa; el formulario debe preguntar si es divisible.
    - 'partes': plan de división (mínimo de vehículos, mínimo desperdicio) cuando es divisible y viable.
    - 'compatibles' cuenta las parejas posibles aunque estén ocupadas; 'disponibles_ahora' solo las libres."""
    return _evaluar_viabilidad(db, payload)


@router.post("/plan-division")
def plan_division(payload: ViabilidadSolicitud, db: Session = Depends(get_db)):
    """Plan de división de una carga (no reserva nada): la evalúa como si fuera divisible."""
    return _evaluar_viabilidad(db, payload.model_copy(update={"es_divisible": True}))


def _serializar_por_envio(db: Session, envio_id):
    """En PostgreSQL, las peticiones del MISMO envío se ponen en fila (candado de la transacción, se suelta al
    confirmar o deshacer). Así un reintento simultáneo nunca compite contra sí mismo ni recibe un falso "sin
    disponibilidad": espera y recibe la reserva ya creada. En otros motores (pruebas con SQLite) no hace nada."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"reserva:{envio_id}"})


def _reserva_activa(db: Session, envio_id):
    return db.query(Reserva).filter(Reserva.envio_id == envio_id, Reserva.estado == "reservada").first()


def _num(valor):
    return float(valor) if valor is not None else None


def _ubicacion_vehiculo(v: Vehiculo):
    if v.latitud is None or v.longitud is None:
        return None
    return {
        "latitud": float(v.latitud),
        "longitud": float(v.longitud),
        "codigo_pais": v.codigo_pais,
        "ubicacion_id": str(v.ubicacion_id) if v.ubicacion_id else None,
        "nombre": v.ubicacion_nombre,
        "tomada_en": v.ubicacion_actualizada_en.isoformat() if v.ubicacion_actualizada_en else None,
        "fuente": v.ubicacion_fuente,
        "fiable": bool(v.ubicacion_confiable),
    }


def _detalle(db: Session, reserva: Reserva, ya_existia: bool = False, ubicacion_previa=None):
    v = db.query(Vehiculo).filter(Vehiculo.id == reserva.vehiculo_id).first()
    c = db.query(Conductor).filter(Conductor.id == reserva.conductor_id).first()
    # `reposicion.desde`: dónde estaba el vehículo al reservarlo (foto tomada ANTES de salir de su sitio)
    desde = ubicacion_previa if ubicacion_previa is not None else (reserva.decision or {}).get("desde")
    return {
        "reserva_id": str(reserva.id),
        "envio_id": str(reserva.envio_id),
        "estado": reserva.estado,
        "modo": reserva.modo,
        "ya_existia": ya_existia,
        "vehiculo": {
            "id": str(v.id),
            "placa": v.placa,
            "tipo": v.tipo,
            "capacidad_kg": float(v.capacidad_kg),
            "capacidad_m3": _num(v.capacidad_m3),
        },
        "conductor": {
            "id": str(c.id),
            "codigo_conductor": c.codigo_conductor,
            "nombre": c.nombre,
        },
        "carga": {"peso_kg": _num(reserva.peso_kg), "volumen_m3": _num(reserva.volumen_m3)},
        "ocupacion": {
            "peso_reservado_kg": float(v.peso_reservado_kg),
            "volumen_reservado_m3": float(v.volumen_reservado_m3),
            "peso_disponible_kg": float(Decimal(str(v.capacidad_kg)) - Decimal(str(v.peso_reservado_kg))),
        },
        "reposicion": {
            "desde": desde,
            "distancia_linea_recta_km": _num(reserva.distancia_origen_km),
            "aproximacion": "linea_recta",
        } if reserva.modo == "exclusiva" else None,
        "decision": reserva.decision,
        "creado_en": reserva.creado_en.isoformat() if reserva.creado_en else None,
        "liberado_en": reserva.liberado_en.isoformat() if reserva.liberado_en else None,
    }


def _sin_disponibilidad(mensaje=None, causa=None, descartadas=None):
    detalle = {
        "codigo": "SIN_DISPONIBILIDAD",
        "mensaje": mensaje or "No hay un vehículo disponible con conductor que cumpla peso, volumen y tipo de carga",
    }
    if causa:
        detalle["causa"] = causa
    if descartadas:
        detalle["descartados"] = descartadas
    return HTTPException(status_code=409, detail=detalle)


@router.post("/", status_code=201)
def reservar(payload: ReservaSolicitud, response: Response, db: Session = Depends(get_db)):
    """Reserva atómica de un vehículo LIBRE con conductor para el envío.
    Con `origen` elige el más cercano a ese punto (línea recta desde su última ubicación real); sin él, el de menor
    capacidad suficiente. Si el candidato mejor ya no sirve (otra petición lo tomó), pasa al siguiente."""
    # Idempotencia: si este envío ya tiene reserva activa, se devuelve la misma
    _serializar_por_envio(db, payload.envio_id)
    existente = _reserva_activa(db, payload.envio_id)
    if existente:
        response.status_code = 200
        return _detalle(db, existente, ya_existia=True)

    requisitos = _requisitos(payload.peso_kg, payload.volumen_m3, payload.tipo_carga, payload.es_hazmat)
    consulta = _compatibles(db, requisitos, ("active",), ("available",))
    if payload.excluir_vehiculos:
        consulta = consulta.filter(Vehiculo.id.notin_(payload.excluir_vehiculos))
    parejas = consulta.all()
    if not parejas:
        raise _sin_disponibilidad()

    origen = None
    if payload.origen is not None:
        origen = seleccion.Origen(payload.origen.latitud, payload.origen.longitud, payload.origen.codigo_pais)
    ordenadas, descartadas = seleccion.ordenar_candidatos(parejas, origen)
    if not ordenadas:
        raise _sin_disponibilidad(
            "Hay vehículos compatibles, pero ninguno está dentro del alcance de reposicionamiento hasta el origen",
            causa="FUERA_DE_ALCANCE", descartadas=descartadas,
        )

    for vehiculo_previo, _, distancia in ordenadas:
        # Se vuelve a leer bloqueando la fila: si otra petición la tiene (SKIP LOCKED) o ya cambió, se pasa al siguiente
        fila = (
            _compatibles(db, requisitos, ("active",), ("available",))
            .filter(Vehiculo.id == vehiculo_previo.id)
            .populate_existing()
            .with_for_update(skip_locked=True)
            .first()
        )
        if fila is None:
            continue
        vehiculo, conductor = fila
        ubicacion_previa = _ubicacion_vehiculo(vehiculo)
        vehiculo.estado = "en_transito"
        conductor.estado = "en_ruta"
        vehiculo.peso_reservado_kg = Decimal(str(payload.peso_kg))      # vehículo libre: la carga a bordo es solo esta
        vehiculo.volumen_reservado_m3 = Decimal(str(payload.volumen_m3)) if payload.volumen_m3 is not None else Decimal("0")
        vehiculo.ubicacion_confiable = False  # va a moverse: su posición solo vuelve a ser fiable cuando Tracking la informe
        reserva = Reserva(
            envio_id=payload.envio_id, vehiculo_id=vehiculo.id, conductor_id=conductor.id,
            peso_kg=payload.peso_kg, volumen_m3=payload.volumen_m3, tipo_carga=payload.tipo_carga,
            es_hazmat=payload.es_hazmat, modo="exclusiva",
            distancia_origen_km=round(distancia, 2) if distancia is not None else None,
            decision={
                "criterio": "cercania_linea_recta" if origen is not None and distancia is not None else "capacidad",
                "candidatos_evaluados": len(ordenadas),
                "descartados": descartadas or None,
                "distancia_linea_recta_km": round(distancia, 2) if distancia is not None else None,
                "sin_ubicacion_fiable": origen is not None and distancia is None,
                "desde": ubicacion_previa,  # foto de dónde estaba: un reintento idempotente la devuelve igual
            },
        )
        db.add(reserva)
        try:
            db.commit()
        except IntegrityError:
            # Otra petición reservó el mismo envío (o el mismo vehículo) justo antes
            db.rollback()
            existente = _reserva_activa(db, payload.envio_id)
            if existente:
                response.status_code = 200
                return _detalle(db, existente, ya_existia=True)
            continue
        db.refresh(reserva)
        return _detalle(db, reserva, ubicacion_previa=ubicacion_previa)

    raise _sin_disponibilidad("El vehículo fue tomado por otra reserva")


@router.post("/compartida", status_code=201)
def reservar_compartida(payload: ReservaCompartidaSolicitud, response: Response, db: Session = Depends(get_db)):
    """Suma un envío al viaje EN CURSO de un vehículo. Bloquea la fila del vehículo y valida, en la misma transacción,
    peso, volumen y compatibilidad (HAZMAT exclusivo; refrigerada solo con refrigerada). Idempotente por envío.
    Si la ruta del vehículo permite o no la recogida lo decide Routing; aquí solo se protege la capacidad."""
    _serializar_por_envio(db, payload.envio_id)
    existente = _reserva_activa(db, payload.envio_id)
    if existente:
        response.status_code = 200
        return _detalle(db, existente, ya_existia=True)

    vehiculo = (
        db.query(Vehiculo).filter(Vehiculo.id == payload.vehiculo_id).populate_existing().with_for_update().first()
    )
    if vehiculo is None:
        raise HTTPException(status_code=404, detail={"codigo": "VEHICULO_NO_ENCONTRADO", "mensaje": "El vehículo no existe"})
    conductor = db.query(Conductor).filter(Conductor.vehiculo_id == vehiculo.id).first()
    activas = db.query(Reserva).filter(Reserva.vehiculo_id == vehiculo.id, Reserva.estado == "reservada").all()
    problema = seleccion.verificar_compartida(
        vehiculo, conductor, activas, payload.peso_kg, payload.volumen_m3, payload.tipo_carga, payload.es_hazmat
    )
    if problema is not None:
        db.rollback()
        raise HTTPException(status_code=409, detail={"codigo": problema[0], "mensaje": problema[1]})

    vehiculo.peso_reservado_kg = Decimal(str(vehiculo.peso_reservado_kg)) + Decimal(str(payload.peso_kg))
    if payload.volumen_m3 is not None:
        vehiculo.volumen_reservado_m3 = Decimal(str(vehiculo.volumen_reservado_m3)) + Decimal(str(payload.volumen_m3))
    reserva = Reserva(
        envio_id=payload.envio_id, vehiculo_id=vehiculo.id, conductor_id=conductor.id,
        peso_kg=payload.peso_kg, volumen_m3=payload.volumen_m3, tipo_carga=payload.tipo_carga,
        es_hazmat=payload.es_hazmat, modo="compartida",
        decision={"criterio": "carga_compartida", "cargas_a_bordo": len(activas)},
    )
    db.add(reserva)
    try:
        db.commit()
    except IntegrityError:
        # El CHECK de la base de datos es la última barrera contra la sobreasignación; o el mismo envío llegó dos veces
        db.rollback()
        existente = _reserva_activa(db, payload.envio_id)
        if existente:
            response.status_code = 200
            return _detalle(db, existente, ya_existia=True)
        raise HTTPException(status_code=409, detail={"codigo": "CAPACIDAD_EXCEDIDA", "mensaje": "La capacidad del vehículo se agotó"})
    db.refresh(reserva)
    return _detalle(db, reserva)


@router.post("/liberar")
def liberar(payload: LiberarSolicitud, db: Session = Depends(get_db)):
    """Libera la reserva del envío. El vehículo y el conductor solo vuelven a quedar libres cuando se libera la
    ÚLTIMA carga a bordo. Idempotente."""
    previa = db.query(Reserva).filter(Reserva.envio_id == payload.envio_id, Reserva.estado == "reservada").first()
    if previa is None:
        anterior = db.query(Reserva).filter(Reserva.envio_id == payload.envio_id).first()
        return {
            "envio_id": str(payload.envio_id),
            "estado": "ya_liberada" if anterior else "sin_reserva",
            "liberado": False,
        }

    # Orden de bloqueo fijo: primero el vehículo, luego el conductor, luego la reserva (evita bloqueos cruzados)
    vehiculo = db.query(Vehiculo).filter(Vehiculo.id == previa.vehiculo_id).populate_existing().with_for_update().first()
    conductor = db.query(Conductor).filter(Conductor.id == previa.conductor_id).populate_existing().with_for_update().first()
    reserva = (
        db.query(Reserva)
        .filter(Reserva.id == previa.id, Reserva.estado == "reservada")
        .populate_existing()
        .with_for_update()
        .first()
    )
    if reserva is None:  # otra petición la liberó mientras esperábamos el bloqueo
        db.rollback()
        return {"envio_id": str(payload.envio_id), "estado": "ya_liberada", "liberado": False}

    reserva.estado = "liberada"
    reserva.liberado_en = datetime.now(timezone.utc)
    if payload.sin_movimiento and reserva.modo == "exclusiva":
        desde = (reserva.decision or {}).get("desde") or {}
        if desde.get("fiable") and vehiculo.latitud is not None:
            vehiculo.ubicacion_confiable = True  # nunca salió de ahí: su última ubicación real sigue siendo válida
    db.flush()
    restantes = db.query(Reserva).filter(Reserva.vehiculo_id == vehiculo.id, Reserva.estado == "reservada").count()
    if restantes == 0:
        vehiculo.peso_reservado_kg = Decimal("0")
        vehiculo.volumen_reservado_m3 = Decimal("0")
        # Solo se revierten los estados que puso la reserva (no se pisa un mantenimiento, por ejemplo)
        if vehiculo.estado == "en_transito":
            vehiculo.estado = "active"
        if conductor.estado == "en_ruta":
            conductor.estado = "available"
    else:
        vehiculo.peso_reservado_kg = max(
            Decimal("0"), Decimal(str(vehiculo.peso_reservado_kg)) - Decimal(str(reserva.peso_kg or 0))
        )
        vehiculo.volumen_reservado_m3 = max(
            Decimal("0"), Decimal(str(vehiculo.volumen_reservado_m3)) - Decimal(str(reserva.volumen_m3 or 0))
        )
    db.commit()
    return {
        "envio_id": str(payload.envio_id),
        "estado": "liberada",
        "liberado": True,
        "vehiculo_id": str(vehiculo.id),
        "conductor_id": str(conductor.id),
        "vehiculo_libre": restantes == 0,
        "cargas_restantes": restantes,
    }


@router.get("/envio/{envio_id}")
def reserva_de_envio(envio_id: UUID, db: Session = Depends(get_db)):
    reserva = (
        db.query(Reserva)
        .filter(Reserva.envio_id == envio_id)
        .order_by(Reserva.creado_en.desc())
        .first()
    )
    if not reserva:
        raise HTTPException(status_code=404, detail="Ese envío no tiene reservas")
    return _detalle(db, reserva)


@router.post("/conciliar")
def conciliar(db: Session = Depends(get_db)):
    """Recalcula la carga reservada de cada vehículo a partir de sus reservas vigentes y corrige las diferencias.
    Informa (sin tocar) los vehículos 'en_transito' que no tienen ninguna reserva. Es seguro repetirlo."""
    correcciones, sin_reserva = [], []
    for v in db.query(Vehiculo).with_for_update().all():
        activas = db.query(Reserva).filter(Reserva.vehiculo_id == v.id, Reserva.estado == "reservada").all()
        peso = sum((Decimal(str(a.peso_kg or 0)) for a in activas), Decimal("0"))
        volumen = sum((Decimal(str(a.volumen_m3 or 0)) for a in activas), Decimal("0"))
        if Decimal(str(v.peso_reservado_kg)) != peso or Decimal(str(v.volumen_reservado_m3)) != volumen:
            correcciones.append({
                "vehiculo_id": str(v.id), "placa": v.placa,
                "peso_antes_kg": float(v.peso_reservado_kg), "peso_despues_kg": float(peso),
                "volumen_antes_m3": float(v.volumen_reservado_m3), "volumen_despues_m3": float(volumen),
            })
            v.peso_reservado_kg, v.volumen_reservado_m3 = peso, volumen
        if not activas and v.estado == "en_transito":
            sin_reserva.append({"vehiculo_id": str(v.id), "placa": v.placa})
    db.commit()
    return {"corregidos": correcciones, "en_transito_sin_reserva": sin_reserva}

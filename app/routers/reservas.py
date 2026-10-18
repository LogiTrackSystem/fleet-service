from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..database import get_db
from ..division import planificar
from ..elegibilidad import HAZMAT_ANIOS_MINIMOS
from ..models import Conductor, Reserva, Vehiculo
from ..schemas import ReservaSolicitud, LiberarSolicitud, ViabilidadSolicitud


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


def _reserva_activa(db: Session, envio_id):
    return db.query(Reserva).filter(Reserva.envio_id == envio_id, Reserva.estado == "reservada").first()


def _detalle(db: Session, reserva: Reserva, ya_existia: bool = False):
    v = db.query(Vehiculo).filter(Vehiculo.id == reserva.vehiculo_id).first()
    c = db.query(Conductor).filter(Conductor.id == reserva.conductor_id).first()
    return {
        "reserva_id": str(reserva.id),
        "envio_id": str(reserva.envio_id),
        "estado": reserva.estado,
        "ya_existia": ya_existia,
        "vehiculo": {
            "id": str(v.id),
            "placa": v.placa,
            "tipo": v.tipo,
            "capacidad_kg": float(v.capacidad_kg),
        },
        "conductor": {
            "id": str(c.id),
            "codigo_conductor": c.codigo_conductor,
            "nombre": c.nombre,
        },
        "creado_en": reserva.creado_en.isoformat() if reserva.creado_en else None,
        "liberado_en": reserva.liberado_en.isoformat() if reserva.liberado_en else None,
    }


@router.post("/", status_code=201)
def reservar(payload: ReservaSolicitud, response: Response, db: Session = Depends(get_db)):
    # Idempotencia: si este envío ya tiene reserva activa, se devuelve la misma
    existente = _reserva_activa(db, payload.envio_id)
    if existente:
        response.status_code = 200
        return _detalle(db, existente, ya_existia=True)

    requisitos = _requisitos(payload.peso_kg, payload.volumen_m3, payload.tipo_carga, payload.es_hazmat)
    consulta = _compatibles(db, requisitos, ("active",), ("available",))

    # Mejor ajuste (menor capacidad suficiente) y bloqueo de las filas elegidas.
    # SKIP LOCKED: si otra petición ya tiene bloqueado un vehículo, este se salta.
    fila = (
        consulta.order_by(Vehiculo.capacidad_kg.asc(), Vehiculo.placa.asc())
        .with_for_update(skip_locked=True)
        .first()
    )
    if fila is None:
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": "SIN_DISPONIBILIDAD",
                "mensaje": "No hay un vehículo disponible con conductor que cumpla peso, volumen y tipo de carga",
            },
        )

    vehiculo, conductor = fila
    vehiculo.estado = "en_transito"
    conductor.estado = "en_ruta"
    reserva = Reserva(envio_id=payload.envio_id, vehiculo_id=vehiculo.id, conductor_id=conductor.id)
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
        raise HTTPException(
            status_code=409,
            detail={"codigo": "SIN_DISPONIBILIDAD", "mensaje": "El vehículo fue tomado por otra reserva"},
        )
    db.refresh(reserva)
    return _detalle(db, reserva)

@router.post("/liberar")
def liberar(payload: LiberarSolicitud, db: Session = Depends(get_db)):
    reserva = (
        db.query(Reserva)
        .filter(Reserva.envio_id == payload.envio_id, Reserva.estado == "reservada")
        .with_for_update()
        .first()
    )
    if reserva is None:
        anterior = db.query(Reserva).filter(Reserva.envio_id == payload.envio_id).first()
        return {
            "envio_id": str(payload.envio_id),
            "estado": "ya_liberada" if anterior else "sin_reserva",
            "liberado": False,
        }

    vehiculo = db.query(Vehiculo).filter(Vehiculo.id == reserva.vehiculo_id).with_for_update().first()
    conductor = db.query(Conductor).filter(Conductor.id == reserva.conductor_id).with_for_update().first()
    # Solo se revierten los estados que puso la reserva (no se pisa un mantenimiento, por ejemplo)
    if vehiculo.estado == "en_transito":
        vehiculo.estado = "active"
    if conductor.estado == "en_ruta":
        conductor.estado = "available"
    reserva.estado = "liberada"
    reserva.liberado_en = datetime.now(timezone.utc)
    db.commit()
    return {
        "envio_id": str(payload.envio_id),
        "estado": "liberada",
        "liberado": True,
        "vehiculo_id": str(vehiculo.id),
        "conductor_id": str(conductor.id),
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
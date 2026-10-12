from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..database import get_db
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
    if codigo == "VOLUMEN_EXCEDIDO":
        return f"Ningún vehículo con conductor soporta {float(payload.volumen_m3):g} m³ junto con ese peso"
    if codigo == "SIN_REFRIGERACION":
        return "Ningún vehículo con refrigeración y conductor puede transportar esta carga"
    return (
        "Ningún vehículo certificado HAZMAT tiene un conductor con certificación HAZMAT "
        f"y al menos {HAZMAT_ANIOS_MINIMOS} años de experiencia"
    )


def _evaluar_viabilidad(db, payload):
    requisitos = _requisitos(payload.peso_kg, payload.volumen_m3, payload.tipo_carga, payload.es_hazmat)
    if _parejas(db, ESTADOS_VEHICULO_OPERATIVOS, ESTADOS_CONDUCTOR_OPERATIVOS).count() == 0:
        return {
            "viable": False,
            "causa": "SIN_FLOTA_OPERATIVA",
            "mensaje": "No hay vehículos operativos con conductor asignado en la flota",
            "compatibles": 0,
            "disponibles_ahora": 0,
        }

    consulta = _parejas(db, ESTADOS_VEHICULO_OPERATIVOS, ESTADOS_CONDUCTOR_OPERATIVOS)
    for codigo, condiciones in requisitos:
        consulta = consulta.filter(*condiciones)
        if consulta.count() == 0:
            maximo = (
                _parejas(db, ESTADOS_VEHICULO_OPERATIVOS, ESTADOS_CONDUCTOR_OPERATIVOS)
                .with_entities(func.max(Vehiculo.capacidad_kg))
                .scalar()
            )
            return {
                "viable": False,
                "causa": codigo,
                "mensaje": _mensaje_viabilidad(codigo, payload, maximo),
                "compatibles": 0,
                "disponibles_ahora": 0,
            }

    return {
        "viable": True,
        "causa": None,
        "mensaje": None,
        "compatibles": consulta.count(),
        "disponibles_ahora": _compatibles(db, requisitos, ("active",), ("available",)).count(),
    }


@router.post("/viabilidad")
def viabilidad(payload: ViabilidadSolicitud, db: Session = Depends(get_db)):
    """¿Existe en la flota alguna pareja vehículo+conductor capaz de transportar esta carga?
    No reserva nada. 'compatibles' cuenta las parejas posibles aunque estén ocupadas;
    'disponibles_ahora' solo las que están libres en este momento."""
    return _evaluar_viabilidad(db, payload)


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
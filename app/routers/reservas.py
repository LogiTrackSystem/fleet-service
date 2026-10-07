from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..database import get_db
from ..elegibilidad import HAZMAT_ANIOS_MINIMOS
from ..models import Conductor, Reserva, Vehiculo
from ..schemas import ReservaSolicitud, LiberarSolicitud

router = APIRouter(prefix="/reservas", tags=["reservas"])


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

    consulta = (
        db.query(Vehiculo, Conductor)
        .join(Conductor, Conductor.vehiculo_id == Vehiculo.id)
        .filter(
            Vehiculo.estado == "active",
            Conductor.estado == "available",
            Vehiculo.capacidad_kg >= payload.peso_kg,
        )
    )
    if payload.volumen_m3 is not None:
        consulta = consulta.filter(or_(Vehiculo.capacidad_m3.is_(None), Vehiculo.capacidad_m3 >= payload.volumen_m3))
    if payload.tipo_carga == "refrigerada":
        consulta = consulta.filter(Vehiculo.capacidad_refrigeracion.is_(True))
    if payload.es_hazmat:
        consulta = consulta.filter(
            Vehiculo.certificado_hazmat.is_(True),
            Conductor.certificacion_hazmat.is_(True),
            Conductor.anios_experiencia >= HAZMAT_ANIOS_MINIMOS,
        )

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
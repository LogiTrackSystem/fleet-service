from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Reserva, Vehiculo
from ..schemas import (
    UbicacionActualizar, UbicacionRespuesta, VehiculoActualizar, VehiculoCreate, VehiculoEstadoActualizar, VehiculoOut,
)

router = APIRouter(prefix="/vehiculos", tags=["vehiculos"])

ESTADOS_VALIDOS = {"active", "en_transito", "en_mantenimiento", "fuera_de_servicio"}


@router.get("/", response_model=list[VehiculoOut])
def list_vehicles(db: Session = Depends(get_db)):
    return db.query(Vehiculo).all()


@router.post("/", response_model=VehiculoOut, status_code=201)
def create_vehicle(payload: VehiculoCreate, db: Session = Depends(get_db)):
    vehicle = Vehiculo(**payload.model_dump())
    db.add(vehicle)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un vehículo con esa placa")
    db.refresh(vehicle)
    return vehicle


@router.get("/placa/{placa}", response_model=VehiculoOut)
def get_vehicle_by_placa(placa: str, db: Session = Depends(get_db)):
    vehicle = db.query(Vehiculo).filter(Vehiculo.placa == placa.strip().upper()).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    return vehicle


@router.get("/{vehicle_id}", response_model=VehiculoOut)
def get_vehicle(vehicle_id: UUID, db: Session = Depends(get_db)):
    vehicle = db.query(Vehiculo).filter(Vehiculo.id == vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    return vehicle


@router.patch("/{vehicle_id}", response_model=VehiculoOut)
def update_vehicle(vehicle_id: UUID, payload: VehiculoActualizar, db: Session = Depends(get_db)):
    vehicle = db.query(Vehiculo).filter(Vehiculo.id == vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    cambios = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if "capacidad_kg" in cambios and Decimal(str(cambios["capacidad_kg"])) < Decimal(str(vehicle.peso_reservado_kg)):
        raise HTTPException(status_code=409, detail={
            "codigo": "CAPACIDAD_MENOR_A_LA_RESERVADA",
            "mensaje": f"El vehículo lleva {float(vehicle.peso_reservado_kg):g} kg reservados; no puede bajar su capacidad por debajo",
        })
    if cambios.get("capacidad_m3") is not None and Decimal(str(cambios["capacidad_m3"])) < Decimal(str(vehicle.volumen_reservado_m3)):
        raise HTTPException(status_code=409, detail={
            "codigo": "CAPACIDAD_MENOR_A_LA_RESERVADA",
            "mensaje": f"El vehículo lleva {float(vehicle.volumen_reservado_m3):g} m³ reservados; no puede bajar su capacidad por debajo",
        })
    for campo, valor in cambios.items():
        setattr(vehicle, campo, valor)
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.patch("/{vehicle_id}/estado", response_model=VehiculoOut)
def update_vehicle_estado(vehicle_id: UUID, payload: VehiculoEstadoActualizar, db: Session = Depends(get_db)):
    if payload.estado not in ESTADOS_VALIDOS:
        raise HTTPException(status_code=422, detail=f"estado debe ser uno de: {', '.join(sorted(ESTADOS_VALIDOS))}")
    vehicle = db.query(Vehiculo).filter(Vehiculo.id == vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    reservado = (
        db.query(Reserva).filter(Reserva.vehiculo_id == vehicle.id, Reserva.estado == "reservada").first() is not None
    )
    nuevo = payload.estado
    if nuevo == "en_transito" and not reservado:
        # 'en_transito' lo pone solo una reserva; ponerlo a mano dejaría un vehículo bloqueado sin envío
        raise HTTPException(
            status_code=422,
            detail={
                "codigo": "ESTADO_GESTIONADO_POR_RESERVAS",
                "mensaje": "El estado 'en_transito' lo asigna el sistema al reservar el vehículo para un envío",
            },
        )
    if nuevo == "active" and reservado:
        # Con un envío en curso no se puede volver a ofrecer el vehículo (se evitarían dobles asignaciones):
        # sigue en tránsito hasta que se libere la reserva
        nuevo = "en_transito"
    vehicle.estado = nuevo
    db.commit()
    db.refresh(vehicle)
    return vehicle


def _aware(momento):
    if momento is None:
        return datetime.now(timezone.utc)
    return momento if momento.tzinfo is not None else momento.replace(tzinfo=timezone.utc)


@router.put("/{vehicle_id}/ubicacion", response_model=UbicacionRespuesta)
def registrar_ubicacion(vehicle_id: UUID, payload: UbicacionActualizar, db: Session = Depends(get_db)):
    """Registra la última ubicación REAL del vehículo (la informa Tracking al llegar o al interrumpirse un viaje; el
    gestor la fija para los vehículos que aún no tienen). Es idempotente y NO retrocede: una posición tomada antes
    que la ya registrada se ignora (`aplicada: false`). El gestor no puede fijarla con el vehículo en viaje."""
    vehicle = db.query(Vehiculo).filter(Vehiculo.id == vehicle_id).populate_existing().with_for_update().first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    tomada = _aware(payload.tomada_en)
    if payload.fuente == "registro_gestor":
        en_viaje = db.query(Reserva).filter(Reserva.vehiculo_id == vehicle.id, Reserva.estado == "reservada").first()
        if en_viaje is not None:
            db.rollback()
            raise HTTPException(status_code=409, detail={
                "codigo": "VEHICULO_EN_VIAJE",
                "mensaje": "El vehículo está en un viaje: su posición la informa el seguimiento, no se puede fijar a mano",
            })
    actual = vehicle.ubicacion_actualizada_en
    if actual is not None:
        actual = actual if actual.tzinfo is not None else actual.replace(tzinfo=timezone.utc)
        if tomada < actual:
            db.rollback()
            return UbicacionRespuesta(aplicada=False, motivo="UBICACION_MAS_RECIENTE_YA_REGISTRADA", vehiculo=vehicle)
        if tomada == actual and db.query(Reserva.id).filter(
                Reserva.vehiculo_id == vehicle.id, Reserva.estado == "reservada").first() is not None:
            # Reenvío tardío de la MISMA posición (la respuesta se perdió y se reintenta) cuando el vehículo ya salió
            # con otra carga: no se le devuelve la confianza a una posición que ya dejó de ser la real.
            db.rollback()
            return UbicacionRespuesta(aplicada=False, motivo="VEHICULO_RESERVADO_POSICION_YA_REGISTRADA", vehiculo=vehicle)
    vehicle.latitud = Decimal(str(payload.latitud))
    vehicle.longitud = Decimal(str(payload.longitud))
    vehicle.codigo_pais = payload.codigo_pais
    vehicle.ubicacion_id = payload.ubicacion_id
    vehicle.ubicacion_nombre = payload.nombre
    vehicle.ubicacion_actualizada_en = tomada
    vehicle.ubicacion_fuente = payload.fuente
    vehicle.ubicacion_confiable = True
    db.commit()
    db.refresh(vehicle)
    return UbicacionRespuesta(aplicada=True, vehiculo=vehicle)


@router.get("/{vehicle_id}/ocupacion")
def ocupacion(vehicle_id: UUID, db: Session = Depends(get_db)):
    """Carga a bordo del vehículo: capacidad, lo reservado, lo que queda y las cargas que lleva."""
    vehicle = db.query(Vehiculo).filter(Vehiculo.id == vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    cargas = (
        db.query(Reserva).filter(Reserva.vehiculo_id == vehicle.id, Reserva.estado == "reservada")
        .order_by(Reserva.creado_en.asc()).all()
    )
    return {
        "vehiculo_id": str(vehicle.id),
        "placa": vehicle.placa,
        "estado": vehicle.estado,
        "capacidad_kg": float(vehicle.capacidad_kg),
        "capacidad_m3": float(vehicle.capacidad_m3) if vehicle.capacidad_m3 is not None else None,
        "peso_reservado_kg": float(vehicle.peso_reservado_kg),
        "volumen_reservado_m3": float(vehicle.volumen_reservado_m3),
        "peso_disponible_kg": float(Decimal(str(vehicle.capacidad_kg)) - Decimal(str(vehicle.peso_reservado_kg))),
        "volumen_disponible_m3": (
            float(Decimal(str(vehicle.capacidad_m3)) - Decimal(str(vehicle.volumen_reservado_m3)))
            if vehicle.capacidad_m3 is not None else None
        ),
        "cargas": [
            {
                "envio_id": str(c.envio_id), "modo": c.modo, "peso_kg": float(c.peso_kg) if c.peso_kg is not None else None,
                "volumen_m3": float(c.volumen_m3) if c.volumen_m3 is not None else None,
                "tipo_carga": c.tipo_carga, "es_hazmat": c.es_hazmat,
            }
            for c in cargas
        ],
    }

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Vehiculo
from ..schemas import VehiculoCreate, VehiculoOut, VehiculoEstadoActualizar, VehiculoActualizar

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
def get_vehicle(vehicle_id: str, db: Session = Depends(get_db)):
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
    for campo, valor in cambios.items():
        setattr(vehicle, campo, valor)
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.patch("/{vehicle_id}/estado", response_model=VehiculoOut)
def update_vehicle_estado(vehicle_id: str, payload: VehiculoEstadoActualizar, db: Session = Depends(get_db)):
    if payload.estado not in ESTADOS_VALIDOS:
        raise HTTPException(status_code=422, detail=f"estado debe ser uno de: {', '.join(sorted(ESTADOS_VALIDOS))}")
    vehicle = db.query(Vehiculo).filter(Vehiculo.id == vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    vehicle.estado = payload.estado
    db.commit()
    db.refresh(vehicle)
    return vehicle
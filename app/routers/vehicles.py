from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Vehiculo
from ..schemas import VehiculoCreate, VehiculoOut

router = APIRouter(prefix="/vehiculos", tags=["vehiculos"])

@router.get("/", response_model=list[VehiculoOut])
def list_vehicles(db: Session = Depends(get_db)):
    return db.query(Vehiculo).all()

@router.post("/", response_model=VehiculoOut, status_code=201)
def create_vehicle(payload: VehiculoCreate, db: Session = Depends(get_db)):
    vehicle = Vehiculo(**payload.model_dump())
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return vehicle

@router.get("/{vehicle_id}", response_model=VehiculoOut)
def get_vehicle(vehicle_id: str, db: Session = Depends(get_db)):
    vehicle = db.query(Vehiculo).filter(Vehiculo.id == vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    return vehicle
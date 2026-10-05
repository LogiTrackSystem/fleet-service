from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Conductor
from ..schemas import ConductorCreate, ConductorOut, ConductorActualizar

router = APIRouter(prefix="/conductores", tags=["conductores"])


@router.get("/", response_model=list[ConductorOut])
def list_drivers(db: Session = Depends(get_db)):
    return db.query(Conductor).all()


@router.post("/", response_model=ConductorOut, status_code=201)
def create_driver(payload: ConductorCreate, db: Session = Depends(get_db)):
    driver = Conductor(**payload.model_dump())
    db.add(driver)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="No se pudo crear el conductor: licencia_numero repetida o vehiculo_id inexistente")
    db.refresh(driver)
    return driver


@router.get("/codigo/{codigo}", response_model=ConductorOut)
def get_driver_by_codigo(codigo: int, db: Session = Depends(get_db)):
    driver = db.query(Conductor).filter(Conductor.codigo_conductor == codigo).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Conductor no encontrado")
    return driver


@router.get("/{conductor_id}", response_model=ConductorOut)
def get_driver(conductor_id: UUID, db: Session = Depends(get_db)):
    driver = db.query(Conductor).filter(Conductor.id == conductor_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Conductor no encontrado")
    return driver


@router.patch("/{conductor_id}", response_model=ConductorOut)
def update_driver(conductor_id: UUID, payload: ConductorActualizar, db: Session = Depends(get_db)):
    driver = db.query(Conductor).filter(Conductor.id == conductor_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Conductor no encontrado")
    cambios = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    for campo, valor in cambios.items():
        setattr(driver, campo, valor)
    db.commit()
    db.refresh(driver)
    return driver
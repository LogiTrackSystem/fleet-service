from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Conductor
from ..schemas import ConductorCreate, ConductorOut

router = APIRouter(prefix="/conductores", tags=["conductores"])

@router.get("/", response_model=list[ConductorOut])
def list_drivers(db: Session = Depends(get_db)):
    return db.query(Conductor).all()

@router.post("/", response_model=ConductorOut, status_code=201)
def create_driver(payload: ConductorCreate, db: Session = Depends(get_db)):
    driver = Conductor(**payload.model_dump())
    db.add(driver)
    db.commit()
    db.refresh(driver)
    return driver
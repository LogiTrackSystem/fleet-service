from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..database import get_db
from ..elegibilidad import errores_de_elegibilidad
from ..models import Conductor, Vehiculo
from ..schemas import ConductorCreate, ConductorOut, ConductorActualizar, VinculoVehiculo

router = APIRouter(prefix="/conductores", tags=["conductores"])


def _validar_vinculo(db: Session, vehiculo_id, categorias, anios, hazmat, conductor_id=None):
    vehiculo = db.query(Vehiculo).filter(Vehiculo.id == vehiculo_id).first()
    if not vehiculo:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")

    consulta = db.query(Conductor).filter(Conductor.vehiculo_id == vehiculo.id)
    if conductor_id is not None:
        consulta = consulta.filter(Conductor.id != conductor_id)
    otro = consulta.first()
    if otro:
        raise HTTPException(
            status_code=409,
            detail=f"El vehículo {vehiculo.placa} ya tiene asignado al conductor {otro.nombre} (código {otro.codigo_conductor})",
        )

    errores = errores_de_elegibilidad(vehiculo, categorias, anios, hazmat)
    if errores:
        raise HTTPException(
            status_code=422,
            detail={"mensaje": "El conductor no es elegible para este vehículo", "errores": errores},
        )
    return vehiculo


@router.get("/", response_model=list[ConductorOut])
def list_drivers(db: Session = Depends(get_db)):
    return db.query(Conductor).all()


@router.post("/", response_model=ConductorOut, status_code=201)
def create_driver(payload: ConductorCreate, db: Session = Depends(get_db)):
    if payload.vehiculo_id is not None:
        _validar_vinculo(
            db, payload.vehiculo_id, payload.categorias_licencia,
            payload.anios_experiencia, payload.certificacion_hazmat,
        )
    driver = Conductor(**payload.model_dump())
    db.add(driver)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="No se pudo crear el conductor: licencia_numero repetida o vehículo ya ocupado")
    db.refresh(driver)
    return driver


@router.get("/auditoria-vinculos")
def auditar_vinculos(db: Session = Depends(get_db)):
    """Revisa los vínculos conductor↔vehículo que ya existen contra las reglas actuales."""
    filas = db.query(Conductor, Vehiculo).join(Vehiculo, Conductor.vehiculo_id == Vehiculo.id).all()
    resultado = []
    for c, v in filas:
        errores = errores_de_elegibilidad(v, c.categorias_licencia, c.anios_experiencia, c.certificacion_hazmat)
        resultado.append({
            "codigo_conductor": c.codigo_conductor,
            "nombre": c.nombre,
            "placa": v.placa,
            "tipo": v.tipo,
            "valido": not errores,
            "errores": errores,
        })
    return resultado


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


@router.put("/{conductor_id}/vehiculo", response_model=ConductorOut)
def vincular_vehiculo(conductor_id: UUID, payload: VinculoVehiculo, db: Session = Depends(get_db)):
    driver = db.query(Conductor).filter(Conductor.id == conductor_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Conductor no encontrado")

    if driver.vehiculo_id == payload.vehiculo_id:
        return driver
    if driver.vehiculo_id is not None:
        raise HTTPException(status_code=409, detail="El conductor ya tiene un vehículo asignado y el vínculo es permanente")

    _validar_vinculo(
        db, payload.vehiculo_id, driver.categorias_licencia,
        driver.anios_experiencia, driver.certificacion_hazmat, conductor_id=driver.id,
    )
    driver.vehiculo_id = payload.vehiculo_id
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ese vehículo acaba de ser asignado a otro conductor")
    db.refresh(driver)
    return driver
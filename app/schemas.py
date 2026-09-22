from pydantic import BaseModel, ConfigDict
from uuid import UUID
from decimal import Decimal
from datetime import date
from typing import Optional

class VehiculoCreate(BaseModel):
    placa: str
    tipo: str
    capacidad_kg: Decimal
    capacidad_m3: Optional[Decimal] = None
    anio: Optional[int] = None
    vencimiento_seguro: Optional[date] = None
    estado: str = "active"
    capacidad_refrigeracion: bool = False
    certificado_hazmat: bool = False

class VehiculoOut(VehiculoCreate):
    id: UUID
    model_config = ConfigDict(from_attributes=True)

class ConductorCreate(BaseModel):
    nombre: str
    licencia_numero: str
    categorias_licencia: Optional[str] = None
    certificacion_hazmat: bool = False
    vehiculo_id: Optional[UUID] = None
    horas_semanales: Decimal = 0
    estado: str = "available"

class ConductorOut(ConductorCreate):
    id: UUID
    model_config = ConfigDict(from_attributes=True)
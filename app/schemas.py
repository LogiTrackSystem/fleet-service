from pydantic import BaseModel, ConfigDict, Field, field_validator
from uuid import UUID
from decimal import Decimal
from datetime import date
from typing import Literal, Optional

TIPOS_VEHICULO = {"furgoneta", "camion", "tractocamion"}
TIPOS_COMBUSTIBLE = {"diesel", "gasolina", "gnv"}
CATEGORIAS_LICENCIA = {"B1", "B2", "B3", "C1", "C2", "C3"}


def normalizar_tipo(valor):
    if valor is None:
        return None
    v = valor.strip().lower().replace("ó", "o")
    if v not in TIPOS_VEHICULO:
        raise ValueError(f"tipo debe ser uno de: {', '.join(sorted(TIPOS_VEHICULO))}")
    return v


def normalizar_combustible(valor):
    if valor is None:
        return None
    v = valor.strip().lower()
    if v not in TIPOS_COMBUSTIBLE:
        raise ValueError(f"tipo_combustible debe ser uno de: {', '.join(sorted(TIPOS_COMBUSTIBLE))}")
    return v


def normalizar_categorias(valor):
    if valor is None:
        return None
    cats = sorted({c.strip().upper() for c in valor.split(",") if c.strip()})
    if not cats:
        raise ValueError("categorias_licencia no puede estar vacía")
    invalidas = [c for c in cats if c not in CATEGORIAS_LICENCIA]
    if invalidas:
        raise ValueError(
            f"categorías no válidas: {', '.join(invalidas)}. Permitidas: {', '.join(sorted(CATEGORIAS_LICENCIA))}"
        )
    return ",".join(cats)


# ---------- Vehículos ----------

class VehiculoBase(BaseModel):
    placa: str
    tipo: str
    capacidad_kg: Decimal = Field(..., gt=0)
    capacidad_m3: Optional[Decimal] = None
    anio: Optional[int] = None
    vencimiento_seguro: Optional[date] = None
    estado: str = "active"
    capacidad_refrigeracion: bool = False
    certificado_hazmat: bool = False
    capacidad_tanque_l: Optional[Decimal] = Field(None, gt=0)
    consumo_km_por_litro: Optional[Decimal] = Field(None, gt=0)
    tipo_combustible: Optional[str] = None


class VehiculoCreate(VehiculoBase):
    @field_validator("placa")
    @classmethod
    def _placa(cls, v):
        return v.strip().upper()

    @field_validator("tipo")
    @classmethod
    def _tipo(cls, v):
        return normalizar_tipo(v)

    @field_validator("tipo_combustible")
    @classmethod
    def _combustible(cls, v):
        return normalizar_combustible(v)


class VehiculoActualizar(BaseModel):
    tipo: Optional[str] = None
    capacidad_kg: Optional[Decimal] = Field(None, gt=0)
    capacidad_m3: Optional[Decimal] = None
    anio: Optional[int] = None
    vencimiento_seguro: Optional[date] = None
    capacidad_refrigeracion: Optional[bool] = None
    certificado_hazmat: Optional[bool] = None
    capacidad_tanque_l: Optional[Decimal] = Field(None, gt=0)
    consumo_km_por_litro: Optional[Decimal] = Field(None, gt=0)
    tipo_combustible: Optional[str] = None

    @field_validator("tipo")
    @classmethod
    def _tipo(cls, v):
        return normalizar_tipo(v)

    @field_validator("tipo_combustible")
    @classmethod
    def _combustible(cls, v):
        return normalizar_combustible(v)


class VehiculoOut(VehiculoBase):
    id: UUID
    model_config = ConfigDict(from_attributes=True)


class VehiculoEstadoActualizar(BaseModel):
    estado: str


# ---------- Conductores ----------

class ConductorBase(BaseModel):
    nombre: str
    licencia_numero: str
    categorias_licencia: Optional[str] = None
    certificacion_hazmat: bool = False
    anios_experiencia: int = Field(0, ge=0)
    vehiculo_id: Optional[UUID] = None
    horas_semanales: Decimal = 0
    estado: str = "available"


class ConductorCreate(ConductorBase):
    @field_validator("categorias_licencia")
    @classmethod
    def _categorias(cls, v):
        return normalizar_categorias(v)


class ConductorActualizar(BaseModel):
    nombre: Optional[str] = None
    categorias_licencia: Optional[str] = None
    certificacion_hazmat: Optional[bool] = None
    anios_experiencia: Optional[int] = Field(None, ge=0)
    horas_semanales: Optional[Decimal] = None

    @field_validator("categorias_licencia")
    @classmethod
    def _categorias(cls, v):
        return normalizar_categorias(v)


class ConductorOut(ConductorBase):
    id: UUID
    codigo_conductor: int
    model_config = ConfigDict(from_attributes=True)

class VinculoVehiculo(BaseModel):
    vehiculo_id: UUID


class ReservaSolicitud(BaseModel):
    envio_id: UUID
    peso_kg: Decimal = Field(..., gt=0)
    volumen_m3: Optional[Decimal] = Field(None, gt=0)
    tipo_carga: Literal["general", "refrigerada"] = "general"
    es_hazmat: bool = False


class LiberarSolicitud(BaseModel):
    envio_id: UUID
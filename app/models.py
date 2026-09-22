import uuid
from sqlalchemy import Column, String, Boolean, Integer, Numeric, Date, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from .database import Base

class Vehiculo(Base):
    __tablename__ = "vehiculos"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    placa = Column(String(10), unique=True, nullable=False)
    tipo = Column(String(50), nullable=False)
    capacidad_kg = Column(Numeric(10, 2), nullable=False)
    capacidad_m3 = Column(Numeric(10, 2), nullable=True)
    anio = Column(Integer, nullable=True)
    vencimiento_seguro = Column(Date, nullable=True)
    estado = Column(String(20), nullable=False, default="active")
    capacidad_refrigeracion = Column(Boolean, nullable=False, default=False)
    certificado_hazmat = Column(Boolean, nullable=False, default=False)

class Conductor(Base):
    __tablename__ = "conductores"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre = Column(String(150), nullable=False)
    licencia_numero = Column(String(50), unique=True, nullable=False)
    categorias_licencia = Column(String(100), nullable=True)
    certificacion_hazmat = Column(Boolean, nullable=False, default=False)
    vehiculo_id = Column(UUID(as_uuid=True), ForeignKey("vehiculos.id"), nullable=True)
    horas_semanales = Column(Numeric(5, 2), default=0)
    estado = Column(String(20), nullable=False, default="available")
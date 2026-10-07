import uuid
from sqlalchemy import Column, String, Boolean, Integer, BigInteger, Numeric, Date, DateTime, ForeignKey, Index, text
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
    capacidad_tanque_l = Column(Numeric(6, 2), nullable=True)
    consumo_km_por_litro = Column(Numeric(5, 2), nullable=True)
    tipo_combustible = Column(String(20), nullable=True)

class Conductor(Base):
    __tablename__ = "conductores"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    codigo_conductor = Column(BigInteger, server_default=text("nextval('seq_codigo_conductor')"), unique=True, nullable=False)
    nombre = Column(String(150), nullable=False)
    licencia_numero = Column(String(50), unique=True, nullable=False)
    categorias_licencia = Column(String(100), nullable=True)
    certificacion_hazmat = Column(Boolean, nullable=False, default=False)
    anios_experiencia = Column(Integer, nullable=False, server_default="0")
    vehiculo_id = Column(UUID(as_uuid=True), ForeignKey("vehiculos.id"), nullable=True, unique=True)
    horas_semanales = Column(Numeric(5, 2), default=0)
    estado = Column(String(20), nullable=False, default="available")


class Reserva(Base):
    __tablename__ = "reservas_flota"
    __table_args__ = (
        Index("uq_reserva_activa_por_envio", "envio_id", unique=True, postgresql_where=text("estado = 'reservada'")),
        Index("uq_reserva_activa_por_vehiculo", "vehiculo_id", unique=True, postgresql_where=text("estado = 'reservada'")),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    envio_id = Column(UUID(as_uuid=True), nullable=False)
    vehiculo_id = Column(UUID(as_uuid=True), ForeignKey("vehiculos.id"), nullable=False)
    conductor_id = Column(UUID(as_uuid=True), ForeignKey("conductores.id"), nullable=False)
    estado = Column(String(20), nullable=False, default="reservada")
    creado_en = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    liberado_en = Column(DateTime(timezone=True), nullable=True)
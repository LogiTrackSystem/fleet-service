import uuid
from sqlalchemy import CheckConstraint, Column, String, Boolean, Integer, BigInteger, Numeric, Date, DateTime, ForeignKey, Index, JSON, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from .database import Base

class Vehiculo(Base):
    __tablename__ = "vehiculos"
    __table_args__ = (
        # Red de seguridad en la base de datos: ninguna combinación de peticiones puede sobrepasar la capacidad
        CheckConstraint("peso_reservado_kg >= 0 AND peso_reservado_kg <= capacidad_kg", name="ck_vehiculos_peso_reservado"),
        CheckConstraint(
            "volumen_reservado_m3 >= 0 AND (capacidad_m3 IS NULL OR volumen_reservado_m3 <= capacidad_m3)",
            name="ck_vehiculos_volumen_reservado",
        ),
    )
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
    # Última ubicación REAL conocida con el vehículo en reposo (en viaje la posición vive en Tracking)
    latitud = Column(Numeric(9, 6), nullable=True)
    longitud = Column(Numeric(9, 6), nullable=True)
    codigo_pais = Column(String(2), nullable=True)
    ubicacion_id = Column(UUID(as_uuid=True), nullable=True)  # ubicación del catálogo de Routing, si coincide con una
    ubicacion_nombre = Column(String(150), nullable=True)
    ubicacion_actualizada_en = Column(DateTime(timezone=True), nullable=True)  # momento en que se tomó la posición
    ubicacion_fuente = Column(String(20), nullable=True)  # registro_gestor | entrega | interrupcion | telemetria
    # False mientras el vehículo está en viaje o aún no llega la posición de su último viaje: no se usa para medir cercanía
    ubicacion_confiable = Column(Boolean, nullable=False, server_default=text("false"))
    # Carga a bordo: suma de las reservas activas (la mantiene el sistema; el CHECK impide sobrepasar la capacidad)
    peso_reservado_kg = Column(Numeric(12, 2), nullable=False, server_default=text("0"))
    volumen_reservado_m3 = Column(Numeric(12, 2), nullable=False, server_default=text("0"))

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
        # Un vehículo tiene a lo sumo UNA reserva "exclusiva" (la que lo despacha); las "compartidas" se suman a ella
        Index(
            "uq_reserva_exclusiva_por_vehiculo", "vehiculo_id", unique=True,
            postgresql_where=text("estado = 'reservada' AND modo = 'exclusiva'"),
            sqlite_where=text("estado = 'reservada' AND modo = 'exclusiva'"),
        ),
        Index("ix_reservas_vehiculo_estado", "vehiculo_id", "estado"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    envio_id = Column(UUID(as_uuid=True), nullable=False)
    vehiculo_id = Column(UUID(as_uuid=True), ForeignKey("vehiculos.id"), nullable=False)
    conductor_id = Column(UUID(as_uuid=True), ForeignKey("conductores.id"), nullable=False)
    estado = Column(String(20), nullable=False, default="reservada")
    creado_en = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    liberado_en = Column(DateTime(timezone=True), nullable=True)
    # Carga que esta reserva ocupa en el vehículo y datos de la decisión (trazabilidad)
    peso_kg = Column(Numeric(12, 2), nullable=True)
    volumen_m3 = Column(Numeric(12, 2), nullable=True)
    tipo_carga = Column(String(20), nullable=True)
    es_hazmat = Column(Boolean, nullable=False, server_default=text("false"))
    modo = Column(String(12), nullable=False, server_default="exclusiva")  # exclusiva | compartida
    distancia_origen_km = Column(Numeric(10, 2), nullable=True)  # en línea recta, del vehículo al origen del envío
    decision = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)

"""ubicación real del vehículo, carga reservada y reservas compartidas

Revision ID: d4e8a1c7b952
Revises: 3a7fe1bab681
Create Date: 2026-10-21 12:00:00

Cambios aditivos. Las reservas activas que ya existían se tratan como "vehículo completo"
(peso y volumen reservados = capacidad) para que nadie les comparta carga por error.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d4e8a1c7b952"
down_revision: Union[str, Sequence[str], None] = "3a7fe1bab681"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- vehículos: ubicación y carga reservada ---
    op.add_column("vehiculos", sa.Column("latitud", sa.Numeric(9, 6), nullable=True))
    op.add_column("vehiculos", sa.Column("longitud", sa.Numeric(9, 6), nullable=True))
    op.add_column("vehiculos", sa.Column("codigo_pais", sa.String(2), nullable=True))
    op.add_column("vehiculos", sa.Column("ubicacion_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("vehiculos", sa.Column("ubicacion_nombre", sa.String(150), nullable=True))
    op.add_column("vehiculos", sa.Column("ubicacion_actualizada_en", sa.DateTime(timezone=True), nullable=True))
    op.add_column("vehiculos", sa.Column("ubicacion_fuente", sa.String(20), nullable=True))
    op.add_column("vehiculos", sa.Column("ubicacion_confiable", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("vehiculos", sa.Column("peso_reservado_kg", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")))
    op.add_column("vehiculos", sa.Column("volumen_reservado_m3", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")))

    # --- reservas: carga que ocupan y trazabilidad ---
    op.add_column("reservas_flota", sa.Column("peso_kg", sa.Numeric(12, 2), nullable=True))
    op.add_column("reservas_flota", sa.Column("volumen_m3", sa.Numeric(12, 2), nullable=True))
    op.add_column("reservas_flota", sa.Column("tipo_carga", sa.String(20), nullable=True))
    op.add_column("reservas_flota", sa.Column("es_hazmat", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("reservas_flota", sa.Column("modo", sa.String(12), nullable=False, server_default="exclusiva"))
    op.add_column("reservas_flota", sa.Column("distancia_origen_km", sa.Numeric(10, 2), nullable=True))
    op.add_column("reservas_flota", sa.Column("decision", postgresql.JSONB(), nullable=True))

    # Reservas vigentes de antes: ocupan el vehículo completo (conservador)
    op.execute("""
        UPDATE reservas_flota r
           SET peso_kg = v.capacidad_kg, volumen_m3 = v.capacidad_m3
          FROM vehiculos v
         WHERE r.vehiculo_id = v.id AND r.estado = 'reservada' AND r.peso_kg IS NULL
    """)
    op.execute("""
        UPDATE vehiculos v
           SET peso_reservado_kg = v.capacidad_kg, volumen_reservado_m3 = COALESCE(v.capacidad_m3, 0)
         WHERE EXISTS (SELECT 1 FROM reservas_flota r WHERE r.vehiculo_id = v.id AND r.estado = 'reservada')
    """)

    # --- restricciones ---
    op.create_check_constraint(
        "ck_vehiculos_peso_reservado", "vehiculos", "peso_reservado_kg >= 0 AND peso_reservado_kg <= capacidad_kg"
    )
    op.create_check_constraint(
        "ck_vehiculos_volumen_reservado", "vehiculos",
        "volumen_reservado_m3 >= 0 AND (capacidad_m3 IS NULL OR volumen_reservado_m3 <= capacidad_m3)",
    )
    op.drop_index("uq_reserva_activa_por_vehiculo", table_name="reservas_flota")
    op.create_index(
        "uq_reserva_exclusiva_por_vehiculo", "reservas_flota", ["vehiculo_id"],
        unique=True, postgresql_where=sa.text("estado = 'reservada' AND modo = 'exclusiva'"),
    )
    op.create_index("ix_reservas_vehiculo_estado", "reservas_flota", ["vehiculo_id", "estado"])


def downgrade() -> None:
    op.drop_index("ix_reservas_vehiculo_estado", table_name="reservas_flota")
    op.drop_index("uq_reserva_exclusiva_por_vehiculo", table_name="reservas_flota")
    op.create_index(
        "uq_reserva_activa_por_vehiculo", "reservas_flota", ["vehiculo_id"],
        unique=True, postgresql_where=sa.text("estado = 'reservada'"),
    )
    op.drop_constraint("ck_vehiculos_volumen_reservado", "vehiculos", type_="check")
    op.drop_constraint("ck_vehiculos_peso_reservado", "vehiculos", type_="check")
    for c in ("decision", "distancia_origen_km", "modo", "es_hazmat", "tipo_carga", "volumen_m3", "peso_kg"):
        op.drop_column("reservas_flota", c)
    for c in ("volumen_reservado_m3", "peso_reservado_kg", "ubicacion_confiable", "ubicacion_fuente",
              "ubicacion_actualizada_en", "ubicacion_nombre", "ubicacion_id", "codigo_pais", "longitud", "latitud"):
        op.drop_column("vehiculos", c)

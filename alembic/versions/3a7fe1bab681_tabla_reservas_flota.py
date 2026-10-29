"""tabla reservas_flota

Revision ID: 3a7fe1bab681
Revises: a5cc19f885bb
Create Date: 2026-10-06 22:27:56.918543

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '3a7fe1bab681'
down_revision: Union[str, Sequence[str], None] = 'a5cc19f885bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        "reservas_flota",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("envio_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vehiculo_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vehiculos.id"), nullable=False),
        sa.Column("conductor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conductores.id"), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False, server_default="reservada"),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("liberado_en", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_reserva_activa_por_envio", "reservas_flota", ["envio_id"],
        unique=True, postgresql_where=sa.text("estado = 'reservada'"),
    )
    op.create_index(
        "uq_reserva_activa_por_vehiculo", "reservas_flota", ["vehiculo_id"],
        unique=True, postgresql_where=sa.text("estado = 'reservada'"),
    )


def downgrade() -> None:
    op.drop_index("uq_reserva_activa_por_vehiculo", table_name="reservas_flota")
    op.drop_index("uq_reserva_activa_por_envio", table_name="reservas_flota")
    op.drop_table("reservas_flota")
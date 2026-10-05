"""codigo conductor experiencia y combustible

Revision ID: 2c5eba2acca5
Revises: a7b69aeffaea
Create Date: 2026-10-05 11:04:58.513384

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c5eba2acca5'
down_revision: Union[str, Sequence[str], None] = 'a7b69aeffaea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS seq_codigo_conductor START WITH 1000000001 MINVALUE 1000000001 MAXVALUE 9999999999")
    op.add_column("conductores", sa.Column("codigo_conductor", sa.BigInteger(), server_default=sa.text("nextval('seq_codigo_conductor')"), nullable=False))
    op.create_unique_constraint("uq_conductores_codigo_conductor", "conductores", ["codigo_conductor"])
    op.execute("ALTER SEQUENCE seq_codigo_conductor OWNED BY conductores.codigo_conductor")
    op.add_column("conductores", sa.Column("anios_experiencia", sa.Integer(), server_default="0", nullable=False))
    op.add_column("vehiculos", sa.Column("capacidad_tanque_l", sa.Numeric(precision=6, scale=2), nullable=True))
    op.add_column("vehiculos", sa.Column("consumo_km_por_litro", sa.Numeric(precision=5, scale=2), nullable=True))
    op.add_column("vehiculos", sa.Column("tipo_combustible", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("vehiculos", "tipo_combustible")
    op.drop_column("vehiculos", "consumo_km_por_litro")
    op.drop_column("vehiculos", "capacidad_tanque_l")
    op.drop_column("conductores", "anios_experiencia")
    op.drop_constraint("uq_conductores_codigo_conductor", "conductores", type_="unique")
    op.drop_column("conductores", "codigo_conductor")
    op.execute("DROP SEQUENCE IF EXISTS seq_codigo_conductor")
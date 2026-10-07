"""un conductor por vehiculo

Revision ID: a5cc19f885bb
Revises: 2c5eba2acca5
Create Date: 2026-10-06 22:21:43.284618

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a5cc19f885bb'
down_revision: Union[str, Sequence[str], None] = '2c5eba2acca5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint("uq_conductores_vehiculo_id", "conductores", ["vehiculo_id"])


def downgrade() -> None:
    op.drop_constraint("uq_conductores_vehiculo_id", "conductores", type_="unique")
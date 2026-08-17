"""initial

Revision ID: 0001_initial
Revises: 
Create Date: 2026-08-09
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Use SQLAlchemy metadata to create tables
    from app import models
    bind = op.get_bind()
    models.Base.metadata.create_all(bind=bind)


def downgrade():
    from app import models
    bind = op.get_bind()
    models.Base.metadata.drop_all(bind=bind)

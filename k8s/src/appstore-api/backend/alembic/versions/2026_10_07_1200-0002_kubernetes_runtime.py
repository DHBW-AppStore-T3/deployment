"""kubernetes runtime

Apps can run as pods (appstore.yaml) instead of OpenStack VMs. Deployments and
approvals record which runtime, and an approval also covers the spec hash and
the image digests. Staging already holds data at 0001, so this is a new
migration instead of a regenerated 0001.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('deployments', sa.Column('runtime', sa.String(length=16), server_default='openstack-vm', nullable=False))
    op.add_column('deployments', sa.Column('k8s_namespace', sa.String(length=63), nullable=True))
    op.add_column('app_version_approvals', sa.Column('runtime', sa.String(length=16), server_default='openstack-vm', nullable=False))
    op.add_column('app_version_approvals', sa.Column('spec_sha256', sa.String(length=64), nullable=True))
    op.add_column('app_version_approvals', sa.Column('image_digests', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('app_version_approvals', 'image_digests')
    op.drop_column('app_version_approvals', 'spec_sha256')
    op.drop_column('app_version_approvals', 'runtime')
    op.drop_column('deployments', 'k8s_namespace')
    op.drop_column('deployments', 'runtime')

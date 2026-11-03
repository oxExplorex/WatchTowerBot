"""Personal archive keys and resumable content migration; no secret in Alembic."""
from alembic import op
import sqlalchemy as sa

revision = "20261104_02"
down_revision = "20261104_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("owner_archive_key",
        sa.Column("owner_id", sa.BigInteger(), primary_key=True),
        sa.Column("public_key", sa.String(), nullable=False),
        sa.Column("encrypted_private_key", sa.String(), nullable=False),
        sa.Column("salt", sa.String(), nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("migration_state", sa.String(), nullable=False),
        sa.Column("migrated_revisions", sa.Integer(), nullable=False),
        sa.Column("migrated_files", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(), nullable=True))
    op.add_column("message_attachment", sa.Column("encryption_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("message_attachment", sa.Column("sources_encryption_version", sa.Integer(), nullable=False, server_default="1"))


def downgrade():
    # Deleting the only protected private keys would irreversibly lose archives.
    raise RuntimeError("Personal archive encryption cannot be downgraded; use a compatible backup")

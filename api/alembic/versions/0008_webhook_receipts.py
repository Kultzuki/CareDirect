"""Durable verified webhook receipts, dedupe and retry outcomes.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "paypal_webhook_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_id", sa.String(100), nullable=False, unique=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("invoice_id", sa.String(64), nullable=True),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.execute("""CREATE TRIGGER immutable_webhook_receipt BEFORE UPDATE
      ON paypal_webhook_events FOR EACH ROW EXECUTE FUNCTION cd_protect_columns(
      'outcome','attempts','error_code','processed_at','updated_at')""")
    op.execute("""CREATE TRIGGER webhook_receipt_no_delete BEFORE DELETE
      ON paypal_webhook_events FOR EACH ROW EXECUTE FUNCTION cd_forbid_mutation()""")


def downgrade():
    raise RuntimeError("0008 preserves verified webhook history; do not delete payment evidence")

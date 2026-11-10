"""One ledger credit per reconciled external payment.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fail rather than silently rewriting immutable history if old duplicate credits exist.
    op.create_index(
        "uq_ledger_external_payment_credit",
        "ledger_entries",
        ["external_payment_id"],
        unique=True,
        postgresql_where=sa.text("entry_type = 'EXTERNAL_PAYMENT'"),
    )


def downgrade() -> None:
    op.drop_index("uq_ledger_external_payment_credit", table_name="ledger_entries")

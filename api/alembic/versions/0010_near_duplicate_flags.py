"""Add advisory near-duplicate questions without changing financial records.

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def _flags(include_near):
    values = [
        "POSSIBLE_EXACT_DUPLICATE",
        "ARITHMETIC_MISMATCH",
        "ADVANCE_PAYMENT_MISMATCH",
        "ESTIMATE_DRIFT",
        "CROSS_DOCUMENT_OVERLAP",
    ]
    if include_near:
        values.append("POSSIBLE_NEAR_DUPLICATE")
    op.drop_constraint(op.f("ck_billing_flags_flagtype"), "billing_flags", type_="check")
    allowed = ", ".join(f"'{value}'" for value in values)
    op.create_check_constraint(
        op.f("ck_billing_flags_flagtype"), "billing_flags", f"flag_type IN ({allowed})"
    )


def upgrade():
    _flags(True)


def downgrade():
    # Existing near-duplicate records prevent downgrade rather than erasing review history.
    _flags(False)

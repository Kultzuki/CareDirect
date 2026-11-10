"""Identifiers and estimate-drift verification.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _flags(include_estimate):
    op.drop_constraint(op.f("ck_billing_flags_flagtype"), "billing_flags", type_="check")
    values = "'POSSIBLE_EXACT_DUPLICATE', 'ARITHMETIC_MISMATCH', 'ADVANCE_PAYMENT_MISMATCH'"
    if include_estimate:
        values += ", 'ESTIMATE_DRIFT'"
    op.create_check_constraint(
        op.f("ck_billing_flags_flagtype"), "billing_flags", f"flag_type IN ({values})"
    )


def _protect():
    op.execute("""CREATE OR REPLACE FUNCTION cd_protect_line_item_source() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF (to_jsonb(NEW) - ARRAY['status', 'status_note', 'updated_at'])
         IS DISTINCT FROM
         (to_jsonb(OLD) - ARRAY['status', 'status_note', 'updated_at']) THEN
        RAISE EXCEPTION 'bill_line_items original values are immutable'
          USING ERRCODE = 'restrict_violation';
      END IF;
      RETURN NEW;
    END $$;""")


def upgrade():
    op.add_column("bill_line_items", sa.Column("code", sa.String(40), nullable=True))
    _protect()
    _flags(True)


def downgrade():
    _flags(False)
    op.drop_column("bill_line_items", "code")
    _protect()

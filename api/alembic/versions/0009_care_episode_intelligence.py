"""Care episode intelligence: episode title, clinical context, document category, cross-document overlap flag.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _flags(include_overlap: bool):
    op.drop_constraint(op.f("ck_billing_flags_flagtype"), "billing_flags", type_="check")
    values = (
        "'POSSIBLE_EXACT_DUPLICATE', 'ARITHMETIC_MISMATCH', 'ADVANCE_PAYMENT_MISMATCH', "
        "'ESTIMATE_DRIFT'"
    )
    if include_overlap:
        values += ", 'CROSS_DOCUMENT_OVERLAP'"
    op.create_check_constraint(
        op.f("ck_billing_flags_flagtype"), "billing_flags", f"flag_type IN ({values})"
    )


def _protect_evidence_documents(with_category: bool):
    cols = (
        "'extraction_status', 'category', 'updated_at'"
        if with_category
        else "'extraction_status', 'updated_at'"
    )
    op.execute(f"""CREATE OR REPLACE TRIGGER evidence_documents_protect_source BEFORE UPDATE ON evidence_documents
      FOR EACH ROW EXECUTE FUNCTION cd_protect_columns({cols});""")


def upgrade():
    op.add_column("care_cases", sa.Column("episode_title", sa.String(200), nullable=True))
    op.add_column("care_cases", sa.Column("clinical_context", sa.Text(), nullable=True))
    op.add_column("evidence_documents", sa.Column("category", sa.String(60), nullable=True))
    _flags(True)
    _protect_evidence_documents(True)


def downgrade():
    _protect_evidence_documents(False)
    _flags(False)
    op.drop_column("evidence_documents", "category")
    op.drop_column("care_cases", "clinical_context")
    op.drop_column("care_cases", "episode_title")

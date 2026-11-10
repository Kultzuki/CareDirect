"""Allow insurance pre-authorisation, settlement and remittance evidence.

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def _types(include_insurance):
    values = ["BILL", "ESTIMATE", "RECEIPT", "PROVIDER_SUPPORTING", "OTHER"]
    if include_insurance:
        values += ["INSURANCE_PREAUTH", "INSURANCE_SETTLEMENT", "INSURER_PAYMENT"]
    allowed = ", ".join(f"'{v}'" for v in values)
    op.drop_constraint(
        op.f("ck_evidence_documents_documenttype"), "evidence_documents", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_evidence_documents_documenttype"),
        "evidence_documents",
        f"document_type IN ({allowed})",
    )


def upgrade():
    _types(True)


def downgrade():
    _types(False)

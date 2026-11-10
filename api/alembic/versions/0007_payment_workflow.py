"""Approved Sandbox payment workflow, durable network reservations and immutable evidence.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    for name, kind in [
        ("state_fingerprint", sa.String(64)),
        ("account_binding", JSONB()),
        ("composition", JSONB()),
        ("purpose", sa.String(1000)),
    ]:
        op.add_column("approval_records", sa.Column(name, kind, nullable=True))
    op.drop_constraint("uq_approval_records_case_ledger_seq", "approval_records", type_="unique")
    op.create_index(
        "uq_approval_records_case_fingerprint",
        "approval_records",
        ["case_id", "state_fingerprint"],
        unique=True,
        postgresql_where=sa.text("state_fingerprint IS NOT NULL"),
    )
    op.create_table(
        "paypal_account_bindings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("client_fingerprint", sa.String(64), nullable=False, index=True),
        sa.Column("merchant_ref", sa.String(64), nullable=False),
        sa.Column("capture_ref", sa.String(64), nullable=False),
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_table(
        "payment_operations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "case_id", sa.Uuid(), sa.ForeignKey("care_cases.id"), nullable=False, unique=True
        ),
        sa.Column(
            "approval_id",
            sa.Uuid(),
            sa.ForeignKey("approval_records.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("stage", sa.String(80), nullable=False),
        sa.Column("paypal_invoice_id", sa.String(64), nullable=True, unique=True),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("stages", JSONB(), nullable=False),
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
    op.add_column("ledger_entries", sa.Column("paypal_payment_ref_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_ledger_entries_paypal_payment_ref_id_paypal_payment_refs"),
        "ledger_entries",
        "paypal_payment_refs",
        ["paypal_payment_ref_id"],
        ["id"],
    )
    op.create_unique_constraint(
        op.f("uq_ledger_entries_paypal_payment_ref_id"), "ledger_entries", ["paypal_payment_ref_id"]
    )
    op.create_index(
        "uq_paypal_payment_capture_global",
        "paypal_payment_refs",
        ["paypal_transaction_id"],
        unique=True,
        postgresql_where=sa.text("payment_source = 'PAYPAL'"),
    )
    op.drop_constraint(op.f("ck_ledger_entries_ledgerentrytype"), "ledger_entries", type_="check")
    op.create_check_constraint(
        op.f("ck_ledger_entries_ledgerentrytype"),
        "ledger_entries",
        "entry_type IN ('BILL_CHARGE','QUERY_HOLD','QUERY_RELEASE','EXTERNAL_PAYMENT','ADJUSTMENT_CREDIT','ADJUSTMENT_DEBIT','PAYPAL_PAYMENT')",
    )
    op.execute("""CREATE TRIGGER payment_operations_protect_reference BEFORE UPDATE ON payment_operations
        FOR EACH ROW EXECUTE FUNCTION cd_protect_columns('state','stage','paypal_invoice_id','error_code','stages','updated_at')""")
    op.execute(
        "CREATE TRIGGER payment_operations_no_delete BEFORE DELETE ON payment_operations FOR EACH ROW EXECUTE FUNCTION cd_forbid_mutation()"
    )
    op.execute(
        "CREATE TRIGGER paypal_account_bindings_append_only BEFORE UPDATE OR DELETE ON paypal_account_bindings FOR EACH ROW EXECUTE FUNCTION cd_forbid_mutation()"
    )
    op.execute("""
    CREATE FUNCTION cd_payment_freeze() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE cid uuid;
    BEGIN
      cid := (to_jsonb(NEW)->>'case_id')::uuid;
      IF TG_OP='UPDATE' AND (to_jsonb(OLD)->>'case_id')::uuid IS DISTINCT FROM cid THEN
        RAISE EXCEPTION 'Financial evidence cannot be moved between cases'
          USING ERRCODE='restrict_violation';
      END IF;
      PERFORM id FROM care_cases WHERE id=cid FOR UPDATE;
      IF EXISTS (SELECT 1 FROM payment_operations WHERE case_id=cid) THEN
        IF TG_TABLE_NAME = 'ledger_entries' AND to_jsonb(NEW)->>'entry_type' = 'PAYPAL_PAYMENT'
          AND to_jsonb(NEW)->>'paypal_payment_ref_id' IS NOT NULL
          AND EXISTS (SELECT 1 FROM paypal_payment_refs p
            WHERE p.id=(to_jsonb(NEW)->>'paypal_payment_ref_id')::uuid
              AND p.case_id=cid AND p.currency=to_jsonb(NEW)->>'currency'
              AND p.amount=(to_jsonb(NEW)->>'amount')::numeric
              AND p.payment_source='PAYPAL' AND p.paypal_status='COMPLETED')
          THEN RETURN NEW; END IF;
        RAISE EXCEPTION 'Case financial evidence is frozen while a payment attempt exists' USING ERRCODE='restrict_violation';
      END IF;
      RETURN NEW;
    END $$;
    """)
    op.execute("""
    CREATE FUNCTION cd_case_payment_freeze() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF EXISTS (SELECT 1 FROM payment_operations WHERE case_id=OLD.id)
         AND (to_jsonb(NEW)-'updated_at') IS DISTINCT FROM (to_jsonb(OLD)-'updated_at') THEN
        RAISE EXCEPTION 'Case identity and business state are frozen while payment attempt exists'
          USING ERRCODE='restrict_violation';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER payment_case_freeze BEFORE UPDATE ON care_cases
      FOR EACH ROW EXECUTE FUNCTION cd_case_payment_freeze();
    """)
    for table in [
        "bills",
        "bill_line_items",
        "external_payments",
        "billing_flags",
        "ledger_entries",
        "evidence_documents",
        "document_extractions",
        "extraction_revisions",
        "provider_links",
        "provider_responses",
        "provider_decisions",
    ]:
        op.execute(
            f"CREATE TRIGGER payment_freeze BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION cd_payment_freeze()"
        )


def downgrade():
    raise RuntimeError(
        "0007 contains immutable payment audit history; use a fresh isolated test schema, never erase financial evidence"
    )

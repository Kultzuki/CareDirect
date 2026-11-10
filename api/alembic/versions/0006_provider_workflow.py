"""Scoped provider responses and payer-reviewed immutable adjustments.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _created(name="created_at"):
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _ledger_types(extended):
    op.drop_constraint(op.f("ck_ledger_entries_ledgerentrytype"), "ledger_entries", type_="check")
    values = "'BILL_CHARGE','QUERY_HOLD','QUERY_RELEASE','EXTERNAL_PAYMENT'"
    if extended:
        values += ",'ADJUSTMENT_CREDIT','ADJUSTMENT_DEBIT'"
    op.create_check_constraint(
        op.f("ck_ledger_entries_ledgerentrytype"), "ledger_entries", f"entry_type IN ({values})"
    )


def upgrade():
    op.create_table(
        "provider_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("care_cases.id"), nullable=False),
        sa.Column("flag_id", sa.Uuid(), sa.ForeignKey("billing_flags.id"), nullable=False),
        sa.Column("line_item_id", sa.Uuid(), sa.ForeignKey("bill_line_items.id"), nullable=False),
        sa.Column("token_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("issued_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        _created(),
        _created("updated_at"),
        sa.CheckConstraint(
            "token_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_provider_links_token_sha256_hex")
        ),
        sa.CheckConstraint(
            "length(btrim(question)) > 0", name=op.f("ck_provider_links_question_required")
        ),
        sa.CheckConstraint(
            "issued_amount > 0", name=op.f("ck_provider_links_issued_amount_positive")
        ),
    )
    op.create_index(op.f("ix_provider_links_case_id"), "provider_links", ["case_id"])
    op.create_index(op.f("ix_provider_links_flag_id"), "provider_links", ["flag_id"])
    op.add_column("provider_responses", sa.Column("provider_link_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_provider_responses_provider_link_id_provider_links"),
        "provider_responses",
        "provider_links",
        ["provider_link_id"],
        ["id"],
    )
    op.create_unique_constraint(
        op.f("uq_provider_responses_provider_link_id"), "provider_responses", ["provider_link_id"]
    )
    op.create_table(
        "provider_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("care_cases.id"), nullable=False),
        sa.Column(
            "response_id",
            sa.Uuid(),
            sa.ForeignKey("provider_responses.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("line_item_id", sa.Uuid(), sa.ForeignKey("bill_line_items.id"), nullable=False),
        sa.Column(
            "decision",
            sa.Enum(
                "ACCEPT",
                "KEEP_OPEN",
                "REJECT",
                name="providerdecisiontype",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("original_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("previous_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("recognized_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("adjustment", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("state_fingerprint", sa.String(64), nullable=False),
        sa.Column("decided_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("actor_label", sa.String(120), nullable=False),
        _created(),
        sa.CheckConstraint(
            "length(btrim(note)) > 0", name=op.f("ck_provider_decisions_note_required")
        ),
        sa.CheckConstraint(
            "original_amount > 0 AND previous_amount >= 0 AND recognized_amount >= 0",
            name=op.f("ck_provider_decisions_amounts_non_negative"),
        ),
        sa.CheckConstraint(
            "recognized_amount = previous_amount + adjustment",
            name=op.f("ck_provider_decisions_adjustment_balance"),
        ),
        sa.CheckConstraint(
            "decision = 'ACCEPT' OR adjustment = 0",
            name=op.f("ck_provider_decisions_non_accept_no_adjustment"),
        ),
    )
    op.create_index(op.f("ix_provider_decisions_case_id"), "provider_decisions", ["case_id"])
    op.add_column("ledger_entries", sa.Column("provider_decision_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_ledger_entries_provider_decision_id_provider_decisions"),
        "ledger_entries",
        "provider_decisions",
        ["provider_decision_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_ledger_provider_decision_type", "ledger_entries", ["provider_decision_id", "entry_type"]
    )
    _ledger_types(True)
    op.execute("""
    CREATE TRIGGER provider_decisions_append_only BEFORE UPDATE OR DELETE ON provider_decisions
      FOR EACH ROW EXECUTE FUNCTION cd_forbid_mutation();
    CREATE TRIGGER provider_links_no_delete BEFORE DELETE ON provider_links
      FOR EACH ROW EXECUTE FUNCTION cd_forbid_mutation();
    CREATE TRIGGER provider_links_protect_scope BEFORE UPDATE ON provider_links
      FOR EACH ROW EXECUTE FUNCTION cd_protect_columns('consumed_at','revoked_at','updated_at');
    """)


def downgrade():
    # Existing adjustments cannot be silently erased; constraint restoration fails closed.
    _ledger_types(False)
    op.drop_constraint("uq_ledger_provider_decision_type", "ledger_entries", type_="unique")
    op.drop_column("ledger_entries", "provider_decision_id")
    op.drop_table("provider_decisions")
    op.drop_column("provider_responses", "provider_link_id")
    op.drop_table("provider_links")

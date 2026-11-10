"""Case-scoped family roles, invitations, internal funding, allocations and notifications.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def _id():
    return sa.Column("id", sa.Uuid(), primary_key=True)


def _case():
    return sa.Column("case_id", sa.Uuid(), sa.ForeignKey("care_cases.id"), nullable=False)


def _user(name="user_id", nullable=False):
    return sa.Column(name, sa.Uuid(), sa.ForeignKey("users.id"), nullable=nullable)


def _created():
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _role_checks(table):
    return (
        sa.CheckConstraint(
            "role IN ('PAYER', 'VIEWER', 'PATIENT')", name=op.f(f"ck_{table}_role_valid")
        ),
        sa.CheckConstraint(
            "role = 'PAYER' OR (NOT can_review AND NOT can_approve)",
            name=op.f(f"ck_{table}_role_permissions"),
        ),
    )


def upgrade():
    op.create_table(
        "family_memberships",
        _id(),
        _case(),
        _user(),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("can_review", sa.Boolean(), nullable=False),
        sa.Column("can_approve", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        _created(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("case_id", "user_id", name="uq_family_membership_case_user"),
        *_role_checks("family_memberships"),
    )
    op.create_table(
        "family_invitations",
        _id(),
        _case(),
        sa.Column("recipient_email", sa.String(254), nullable=False),
        sa.Column("token_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("can_review", sa.Boolean(), nullable=False),
        sa.Column("can_approve", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _user("created_by"),
        _user("accepted_by", True),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        _created(),
        *_role_checks("family_invitations"),
    )
    op.create_table(
        "family_ledger_entries",
        _id(),
        _case(),
        _user(),
        sa.Column("entry_type", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("contributed_on", sa.Date(), nullable=False),
        sa.Column("reference", sa.String(120)),
        sa.Column("reverses_id", sa.Uuid(), sa.ForeignKey("family_ledger_entries.id"), unique=True),
        sa.Column("request_id", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        _user("created_by"),
        _created(),
        sa.UniqueConstraint("case_id", "request_id", name="uq_family_ledger_request"),
        sa.CheckConstraint("amount > 0", name=op.f("ck_family_ledger_entries_amount_positive")),
        sa.CheckConstraint(
            "entry_type IN ('CONTRIBUTION', 'REVERSAL')",
            name=op.f("ck_family_ledger_entries_type_valid"),
        ),
        sa.CheckConstraint(
            "(entry_type = 'REVERSAL') = (reverses_id IS NOT NULL)",
            name=op.f("ck_family_ledger_entries_reversal_reference"),
        ),
    )
    op.create_table(
        "family_allocation_plans",
        _id(),
        _case(),
        sa.Column("line_item_id", sa.Uuid(), sa.ForeignKey("bill_line_items.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("source_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("shares", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("request_id", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        _user("created_by"),
        _created(),
        sa.UniqueConstraint("case_id", "request_id", name="uq_family_allocation_request"),
        sa.UniqueConstraint("line_item_id", "version", name="uq_family_allocation_line_version"),
        sa.CheckConstraint("version > 0", name=op.f("ck_family_allocation_plans_version_positive")),
    )
    op.create_table(
        "family_notifications",
        _id(),
        _case(),
        _user(),
        sa.Column("audit_event_id", sa.Uuid(), sa.ForeignKey("audit_events.id"), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("actor_label", sa.String(120), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        _created(),
        sa.UniqueConstraint("user_id", "audit_event_id", name="uq_family_notification_event"),
    )
    indexes = {
        "family_memberships": ("case_id", "user_id"),
        "family_invitations": ("case_id",),
        "family_ledger_entries": ("case_id",),
        "family_allocation_plans": ("case_id", "line_item_id"),
        "family_notifications": ("case_id", "user_id"),
    }
    for table, columns in indexes.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])
        op.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION cd_forbid_mutation();"
        )
    for table in ("family_ledger_entries", "family_allocation_plans"):
        op.execute(
            f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION cd_forbid_mutation();"
        )
    for table, columns in {
        "family_memberships": "'role', 'can_review', 'can_approve', 'active', 'updated_at'",
        "family_invitations": "'accepted_by', 'accepted_at', 'revoked_at'",
        "family_notifications": "'read_at'",
    }.items():
        op.execute(
            f"CREATE TRIGGER {table}_protect BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION cd_protect_columns({columns});"
        )


def downgrade():
    # Never erase financial history via a routine downgrade.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM family_ledger_entries) OR "
        "EXISTS (SELECT 1 FROM family_allocation_plans) THEN "
        "RAISE EXCEPTION 'family financial history must be preserved'; END IF; END $$;"
    )
    for table in (
        "family_notifications",
        "family_allocation_plans",
        "family_ledger_entries",
        "family_invitations",
        "family_memberships",
    ):
        op.drop_table(table)

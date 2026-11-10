"""Synthetic family collaboration; funding never becomes a hospital payment credit."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app import family
from app import services as svc
from app.errors import Forbidden, ImmutableRecordError
from app.models import FamilyInvitation, FamilyLedgerEntry, FamilyNotification
from app.states import CaseStatus, UserRole


@pytest.fixture
def case(db, actor):
    return svc.create_case(db, actor, patient_alias="Synthetic parents", currency="INR")


def relative(db, name="Sibling"):
    return svc.create_user(
        db, name, UserRole.RELATIVE, email=f"{uuid4().hex}@example.invalid", is_demo=True
    )


def join(db, actor, case, user, role="PAYER", review=False, approve=False):
    invitation = family.invite(
        db,
        actor,
        case.id,
        family.InviteRequest(
            recipient_email=user.email, role=role, can_review=review, can_approve=approve
        ),
    )
    member = svc.Actor(user=user, label=user.display_name)
    family.accept_invitation(db, member, invitation["token"])
    return member, invitation


def test_invitation_requires_matching_identity_and_membership_before_access(db, actor, case):
    user = relative(db)
    outsider = svc.Actor(user=user, label="Invited sibling")
    with pytest.raises(Forbidden):
        svc._require_case_member(case, outsider)
    invitation = family.invite(db, actor, case.id, family.InviteRequest(recipient_email=user.email))
    row = db.scalar(select(FamilyInvitation).where(FamilyInvitation.case_id == case.id))
    assert row.token_sha256 != invitation["token"]
    with pytest.raises(Forbidden):
        family.accept_invitation(db, actor, invitation["token"])
    family.accept_invitation(db, outsider, invitation["token"])
    assert family.access(case, outsider)["can_view"]
    assert not family.access(case, outsider)["can_review"]
    assert not family.access(case, outsider)["can_approve"]


def test_three_siblings_contribute_60000_without_crediting_hospital_or_paypal(db, actor, case):
    before = len(svc.case_ledger(db, case.id))
    people = [relative(db, name) for name in ("Daughter USA", "Son UK", "Son India")]
    for user, amount in zip(people, ("30000", "20000", "10000"), strict=True):
        member, _ = join(db, actor, case, user)
        body = family.ContributionRequest(
            user_id=user.id,
            amount=amount,
            currency="INR",
            contributed_on=date(2026, 11, 9),
            note="Synthetic family contribution",
            request_id=uuid4().hex,
        )
        first = family.contribute(db, member, case.id, body)
        assert family.contribute(db, member, case.id, body).id == first.id
    result = family.workspace(db, actor, case.id)
    assert result["total_contributions"] == "60000.00"
    assert sorted(m["contributions"] for m in result["members"] if not m["is_owner"]) == [
        "10000.00",
        "20000.00",
        "30000.00",
    ]
    assert len(svc.case_ledger(db, case.id)) == before
    assert svc.get_buckets(db, case).already_paid == 0


def test_review_and_payment_approval_are_independent(db, actor, case):
    reviewer, _ = join(db, actor, case, relative(db), review=True)
    approver, _ = join(db, actor, case, relative(db), approve=True)
    bill = svc.add_bill(
        db,
        reviewer,
        case.id,
        svc.BillInput(
            provider_name="Demo hospital",
            currency="INR",
            lines=[svc.LineInput(1, "Consultation", Decimal("1000"))],
        ),
    )
    svc.accept_line(db, reviewer, bill.line_items[0].id)
    svc.transition_case(db, reviewer, case.id, CaseStatus.READY_FOR_APPROVAL)
    with pytest.raises(Forbidden):
        svc.record_approval(db, reviewer, case.id, Decimal("1000"), "Demo hospital")
    with pytest.raises(Forbidden):
        svc.accept_line(db, approver, bill.line_items[0].id)
    approval = svc.record_approval(db, approver, case.id, Decimal("1000"), "Demo hospital")
    assert approval.approved_by == approver.user_id


@pytest.mark.parametrize("role", ["VIEWER", "PATIENT"])
def test_readonly_roles_cannot_write_finances_invite_or_escalate(db, actor, case, role):
    member, _ = join(db, actor, case, relative(db), role=role)
    assert family.workspace(db, member, case.id)["access"]["can_view"]
    with pytest.raises(Forbidden):
        svc.run_checks(db, member, case.id)
    with pytest.raises(Forbidden):
        family.contribute(
            db,
            member,
            case.id,
            family.ContributionRequest(
                user_id=member.user_id,
                amount="1",
                currency="INR",
                contributed_on=date(2026, 11, 9),
                note="No authority",
                request_id=uuid4().hex,
            ),
        )
    with pytest.raises(Forbidden):
        family.change_member(
            db,
            member,
            case.id,
            member.user_id,
            family.MemberRequest(
                role="PAYER", can_review=True, can_approve=True, note="No authority"
            ),
        )


def test_revoke_member_blocks_replay_and_preserves_contribution_history(db, actor, case):
    member, invitation = join(db, actor, case, relative(db))
    family.contribute(
        db,
        member,
        case.id,
        family.ContributionRequest(
            user_id=member.user_id,
            amount="10",
            currency="INR",
            contributed_on=date(2026, 11, 9),
            note="Recorded",
            request_id=uuid4().hex,
        ),
    )
    family.change_member(
        db,
        actor,
        case.id,
        member.user_id,
        family.MemberRequest(role="PAYER", active=False, note="Access removed"),
    )
    with pytest.raises(Forbidden):
        family.workspace(db, member, case.id)
    with pytest.raises(Forbidden):
        family.accept_invitation(db, member, invitation["token"])
    assert family.workspace(db, actor, case.id)["total_contributions"] == "10.00"


def test_contribution_reversal_is_once_only_and_retains_original(db, actor, case):
    original = family.contribute(
        db,
        actor,
        case.id,
        family.ContributionRequest(
            user_id=actor.user_id,
            amount="50",
            currency="INR",
            contributed_on=date(2026, 11, 9),
            note="Recorded",
            request_id=uuid4().hex,
        ),
    )
    body = family.ReversalRequest(note="Correction to internal record", request_id=uuid4().hex)
    reversal = family.reverse_contribution(db, actor, case.id, original.id, body)
    assert family.reverse_contribution(db, actor, case.id, original.id, body).id == reversal.id
    assert original.amount == Decimal("50")
    assert family.workspace(db, actor, case.id)["total_contributions"] == "0.00"
    with pytest.raises(svc.DomainError):
        family.reverse_contribution(
            db,
            actor,
            case.id,
            original.id,
            family.ReversalRequest(note="Second reversal", request_id=uuid4().hex),
        )


def test_allocations_bound_to_current_reviewed_expense_and_no_overallocation(db, actor, case):
    member, _ = join(db, actor, case, relative(db))
    bill = svc.add_bill(
        db,
        actor,
        case.id,
        svc.BillInput(
            provider_name="Demo hospital",
            currency="INR",
            lines=[svc.LineInput(1, "Consultation", Decimal("1000"))],
        ),
    )
    svc.accept_line(db, actor, bill.line_items[0].id)
    expense = family.workspace(db, actor, case.id)["expenses"][0]
    body = family.AllocationRequest(
        line_item_id=expense["id"],
        source_fingerprint=expense["source_fingerprint"],
        shares=[
            family.Share(user_id=actor.user_id, amount="600"),
            family.Share(user_id=member.user_id, amount="400"),
        ],
        note="Shared expense",
        request_id=uuid4().hex,
    )
    first = family.allocate(db, actor, case.id, body)
    assert family.allocate(db, actor, case.id, body).id == first.id
    assert family.workspace(db, actor, case.id)["expenses"][0]["unallocated"] == "0.00"
    body.shares[0].amount = Decimal("700")
    body.request_id = uuid4().hex
    with pytest.raises(svc.ValidationFailed):
        family.allocate(db, actor, case.id, body)
    svc.query_line(db, actor, bill.line_items[0].id, "Clarify this charge")
    assert family.workspace(db, actor, case.id)["expenses"][0]["allocation_stale"]


def test_inapp_notifications_scoped_to_member_and_mark_read(db, actor, case):
    member, _ = join(db, actor, case, relative(db))
    svc.run_checks(db, actor, case.id)
    items = family.workspace(db, member, case.id)["notifications"]
    assert items and items[0]["read_at"] is None
    with pytest.raises(svc.NotFound):
        family.mark_read(db, actor, case.id, items[0]["id"])
    family.mark_read(db, member, case.id, items[0]["id"])
    assert db.get(FamilyNotification, items[0]["id"]).read_at is not None


def test_shared_case_list_dashboard_and_history_are_authorized(db, actor, case, client, headers):
    user = relative(db)
    member, _ = join(db, actor, case, user)
    own = {"X-Demo-User-Id": str(user.id)}
    assert str(case.id) in [c["id"] for c in client.get("/api/cases", headers=own).json()]
    assert str(case.id) in [
        c["id"] for c in client.get("/api/dashboard", headers=own).json()["cases"]
    ]
    assert client.get(f"/api/cases/{case.id}/evidence", headers=own).status_code == 200
    assert client.get(f"/api/cases/{case.id}/family", headers=own).status_code == 200
    stranger = relative(db)
    assert (
        client.get(
            f"/api/cases/{case.id}/family", headers={"X-Demo-User-Id": str(stranger.id)}
        ).status_code
        == 403
    )


def test_invitation_revocation_and_expiry(db, actor, case):
    user = relative(db)
    invite = family.invite(db, actor, case.id, family.InviteRequest(recipient_email=user.email))
    family.revoke_invitation(db, actor, case.id, invite["id"])
    with pytest.raises(Forbidden):
        family.accept_invitation(db, svc.Actor(user, "Sibling"), invite["token"])
    second = family.invite(db, actor, case.id, family.InviteRequest(recipient_email=user.email))
    with patch("app.services._now", return_value=second["expires_at"] + timedelta(seconds=1)):
        with pytest.raises(Forbidden):
            family.accept_invitation(db, svc.Actor(user, "Sibling"), second["token"])


def test_family_ledger_immutable_at_orm_and_database(db, actor, case):
    row = family.contribute(
        db,
        actor,
        case.id,
        family.ContributionRequest(
            user_id=actor.user_id,
            amount="10",
            currency="INR",
            contributed_on=date(2026, 11, 9),
            note="Recorded",
            request_id=uuid4().hex,
        ),
    )
    with pytest.raises(ImmutableRecordError), db.begin_nested():
        row.amount = Decimal("20")
        db.flush()
    assert db.get(FamilyLedgerEntry, row.id).amount == Decimal("10")
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(
            text("UPDATE family_ledger_entries SET amount = 20 WHERE id = :id"), {"id": row.id}
        )


def test_payment_permission_changes_invalidate_approval_before_any_remote_post(db, actor):
    from app import payments
    from tests.test_payments import FakePayPal, approved

    fake = FakePayPal()
    case, _, approval = approved(db, actor, fake)
    join(db, actor, case, relative(db), role="VIEWER")
    with pytest.raises(svc.DomainError, match="stale"):
        payments.start_invoice(db, actor, case.id, fake, approval.id)
    assert fake.posts == []


def test_revocation_during_payment_preparation_stops_further_posts(db, actor):
    from app import payments
    from app.models import PaymentOperation
    from tests.test_payments import FakePayPal, payment_case

    fake = FakePayPal()
    case, _ = payment_case(db, actor)
    member, _ = join(db, actor, case, relative(db), approve=True)
    payments.verify_binding(db, actor, case.id, fake)
    preview = payments.preview(db, case, fake)
    approval = payments.approve(
        db,
        actor,
        case.id,
        fake,
        state_fingerprint=preview["state_fingerprint"],
        amount="190.00",
        currency="USD",
        purpose="Synthetic review",
        confirmed=True,
    )
    request = fake.request

    def revoke_after_create(method, path, body=None, request_id=None):
        response = request(method, path, body, request_id)
        if path == "/v2/invoicing/invoices":
            family.change_member(
                db,
                actor,
                case.id,
                member.user_id,
                family.MemberRequest(
                    role="PAYER", active=False, note="Permission removed during preparation"
                ),
            )
        return response

    fake.request = revoke_after_create
    payments.start_invoice(db, actor, case.id, fake, approval.id)
    assert len(fake.posts) == 1
    operation = db.scalar(select(PaymentOperation).where(PaymentOperation.case_id == case.id))
    assert operation.error_code == "FAMILY_PERMISSION_CHANGED"
    assert "SEND" not in operation.stages


def test_owner_can_delegate_approval_and_remove_own_approval_permission(db, actor, case):
    family.change_member(
        db,
        actor,
        case.id,
        actor.user_id,
        family.MemberRequest(
            role="PAYER",
            can_review=True,
            can_approve=False,
            note="Another sibling approves payments",
        ),
    )
    assert family.access(case, actor)["can_manage"]
    assert family.access(case, actor)["can_review"]
    with pytest.raises(Forbidden):
        svc._require_payment_approver(case, actor)

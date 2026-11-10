"""Provider proposals are evidence; only the payer's reviewed decision changes money."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import providers
from app import services as svc
from app.errors import DomainError, Forbidden, ImmutableRecordError, ValidationFailed
from app.models import BillingFlag, ProviderDecision, ProviderLink, ProviderResponse
from app.seed import seed
from app.states import (
    FlagStatus,
    FlagType,
    LedgerEntryType,
    ProviderDecisionType,
    ProviderResponseType,
)


@pytest.fixture
def context(db):
    case = seed(db)
    actor = svc.Actor(user=case.payer, label="PAYER:demo")
    [flag] = svc.case_flags(db, case.id)
    line = next(li for li in svc.case_lines(db, case.id) if li.status == "QUERIED")
    return case, actor, flag, line


def proposal(db, context, kind=ProviderResponseType.CORRECT, amount="1500.00"):
    case, actor, flag, line = context
    link, token = providers.create_link(db, actor, flag.id, line.id, "Please clarify this row.")
    response = providers.respond(
        db,
        token,
        kind,
        "A synthetic billing correction.",
        "Demo desk",
        None if kind != ProviderResponseType.CORRECT else Decimal(amount),
    )
    return link, token, response


@pytest.mark.parametrize(
    "kind,amount,target",
    [
        (ProviderResponseType.ACCEPT, None, "0.00"),
        (ProviderResponseType.CORRECT, "1500.00", "1500.00"),
        (ProviderResponseType.CORRECT, "2500.00", "2500.00"),
        (ProviderResponseType.EXPLAIN, None, "2000.00"),
    ],
)
def test_proposal_has_no_effect_until_payer_accepts(db, context, kind, amount, target):
    case, actor, flag, line = context
    original = svc.get_buckets(db, case)
    link, token, response = proposal(db, context, kind, amount)
    assert svc.get_buckets(db, case) == original
    p = providers.preview(db, actor, response.id)
    assert p["proposed_amount"] == Decimal(target) and p["can_accept"]
    record = providers.decide(
        db,
        actor,
        response.id,
        ProviderDecisionType.ACCEPT,
        "Reviewed the proposed resolution.",
        p["state_fingerprint"],
    )
    b = svc.get_buckets(db, case)
    assert b.original_bill_total == Decimal("25000.00")
    assert b.adjustments == Decimal(target) - Decimal("2000.00")
    assert b.bill_total == b.original_bill_total + b.adjustments
    assert b.queried == Decimal("0") and b.payable_now == Decimal("19000") + Decimal(target)
    assert b.consistent and b.invariant_holds
    assert line.line_total == Decimal("2000")  # Original source never overwritten.
    assert record.recognized_amount == Decimal(target)
    with pytest.raises(DomainError):
        providers.decide(
            db,
            actor,
            response.id,
            ProviderDecisionType.ACCEPT,
            "Duplicate click",
            p["state_fingerprint"],
        )
    assert len(db.scalars(select(ProviderDecision)).all()) == 1


@pytest.mark.parametrize("decision", [ProviderDecisionType.REJECT, ProviderDecisionType.KEEP_OPEN])
def test_reject_or_keep_open_preserves_hold_and_allows_fresh_question(db, context, decision):
    case, actor, flag, line = context
    _, token, response = proposal(db, context)
    p = providers.preview(db, actor, response.id)
    providers.decide(
        db, actor, response.id, decision, "Please provide more evidence.", p["state_fingerprint"]
    )
    assert svc.get_buckets(db, case).queried == Decimal("2000")
    assert flag.status == "OPEN" and line.status == "QUERIED"
    _, fresh = providers.create_link(
        db, actor, flag.id, line.id, "Please clarify the remaining issue."
    )
    assert fresh != token
    with pytest.raises(Forbidden):
        providers.portal(db, token)


def test_requery_after_correction_holds_adjusted_amount(db, context):
    case, actor, flag, line = context
    _, _, response = proposal(db, context)
    p = providers.preview(db, actor, response.id)
    providers.decide(
        db, actor, response.id, ProviderDecisionType.ACCEPT, "Accepted", p["state_fingerprint"]
    )
    svc.query_line(db, actor, line.id, "Another question about the recognized charge.")
    b = svc.get_buckets(db, case)
    assert b.queried == Decimal("1500.00") and b.consistent
    svc.accept_line(db, actor, line.id, "Question answered offline.")
    assert svc.get_buckets(db, case).queried == 0
    assert svc.get_buckets(db, case).consistent


def test_reopen_corrected_charge_keeps_prior_decision_and_starts_new_round(db, context):
    case, actor, flag, line = context
    _, old, response = proposal(db, context)
    p = providers.preview(db, actor, response.id)
    providers.decide(
        db,
        actor,
        response.id,
        ProviderDecisionType.ACCEPT,
        "Accepted the first correction",
        p["state_fingerprint"],
    )
    svc.query_line(db, actor, line.id, "Please clarify another detail", flag.id)
    assert flag.status == FlagStatus.OPEN
    link, token = providers.create_link(db, actor, flag.id, line.id, "A new specific question.")
    assert link.issued_amount == Decimal("1500") and token != old
    assert providers.portal(db, token)["line"]["recognized_amount"] == Decimal("1500")
    assert len(db.scalars(select(ProviderDecision)).all()) == 1


def _three_repeats(db, actor):
    case = svc.create_case(db, actor, patient_alias="Synthetic repeated rows", currency="USD")
    bill = svc.add_bill(
        db,
        actor,
        case.id,
        svc.BillInput(
            provider_name="Synthetic Clinic",
            currency="USD",
            printed_total=Decimal("250"),
            lines=[
                svc.LineInput(1, "Visit", Decimal("190")),
                *(
                    svc.LineInput(
                        n,
                        "Panel",
                        Decimal("20"),
                        service_date=date(2026, 11, 9),
                        quantity=Decimal("1"),
                        unit_price=Decimal("20"),
                    )
                    for n in (2, 3, 4)
                ),
            ],
        ),
    )
    for line in bill.line_items:
        svc.accept_line(db, actor, line.id)
    [flag] = svc.run_checks(db, actor, case.id)
    return case, bill, flag


def test_two_held_repeats_resolve_independently_with_one_aggregate_flag(db, actor):
    case, bill, flag = _three_repeats(db, actor)
    second, third = bill.line_items[2:]
    for line in (second, third):
        svc.query_line(db, actor, line.id, "Please clarify this repeated row", flag.id)
    links = [
        providers.create_link(db, actor, flag.id, line.id, "Is this row repeated?")
        for line in (second, third)
    ]
    responses = [
        providers.respond(
            db, token, ProviderResponseType.ACCEPT, "This synthetic row is credited.", "Demo desk"
        )
        for _, token in links
    ]
    for i, response in enumerate(responses):
        p = providers.preview(db, actor, response.id)
        assert p["can_accept"], p["blockers"]
        providers.decide(
            db,
            actor,
            response.id,
            ProviderDecisionType.ACCEPT,
            "Reviewed this row separately.",
            p["state_fingerprint"],
        )
        b = svc.get_buckets(db, case)
        assert b.consistent and b.queried == Decimal("20") * (1 - i)
        assert flag.status == (FlagStatus.PROVIDER_RESPONDED if i == 0 else FlagStatus.RESOLVED)
    assert svc.get_buckets(db, case).bill_total == Decimal("210")


def test_resolving_one_repeat_does_not_silently_clear_other_accepted_repeat(db, actor):
    case, bill, flag = _three_repeats(db, actor)
    line = bill.line_items[2]
    svc.query_line(db, actor, line.id, "Please clarify this repeated row", flag.id)
    _, token = providers.create_link(db, actor, flag.id, line.id, "Is this row repeated?")
    response = providers.respond(db, token, ProviderResponseType.ACCEPT, "Credit this row", "Desk")
    p = providers.preview(db, actor, response.id)
    providers.decide(
        db,
        actor,
        response.id,
        ProviderDecisionType.ACCEPT,
        "Credit only the scoped row",
        p["state_fingerprint"],
    )
    assert flag.status == FlagStatus.OPEN
    assert any("possible duplicate" in blocker for blocker in svc.approval_blockers(db, case))
    # The payer can review the remaining finding explicitly without rewriting this decision.
    svc.change_flag_status(
        db,
        actor,
        flag.id,
        FlagStatus.DISMISSED,
        "The remaining repeated row has separate supplied evidence.",
    )
    assert svc.get_buckets(db, case).consistent


def test_overlapping_flag_can_be_reviewed_without_bypassing_pending_proposal(db, context):
    case, actor, flag, line = context
    overlap = BillingFlag(
        case_id=case.id,
        bill_id=line.bill_id,
        flag_type=FlagType.ARITHMETIC_MISMATCH,
        line_item_ids=[str(line.id)],
        amount_involved=line.line_total,
        explanation="Synthetic separate arithmetic question",
        evidence={},
        rule_id="test",
        rule_version="1",
        dedupe_key="synthetic-overlap",
    )
    db.add(overlap)
    db.commit()
    _, _, response = proposal(db, context)
    p = providers.preview(db, actor, response.id)
    assert not p["can_accept"] and any("Another open question" in b for b in p["blockers"])
    svc.change_flag_status(
        db, actor, overlap.id, FlagStatus.DISMISSED, "Reviewed the independent arithmetic evidence."
    )
    assert providers.preview(db, actor, response.id)["can_accept"]


def test_prior_round_decisions_do_not_clear_a_reopened_unanswered_line(db, actor):
    case, bill, flag = _three_repeats(db, actor)
    second, third = bill.line_items[2:]
    for line in (second, third):
        svc.query_line(db, actor, line.id, "First review round", flag.id)
        _, token = providers.create_link(db, actor, flag.id, line.id, "Please review this row.")
        response = providers.respond(
            db,
            token,
            ProviderResponseType.CORRECT,
            "Correct this row to fifteen.",
            "Desk",
            Decimal("15"),
        )
        p = providers.preview(db, actor, response.id)
        providers.decide(
            db,
            actor,
            response.id,
            ProviderDecisionType.ACCEPT,
            "Accepted this row correction.",
            p["state_fingerprint"],
        )
    assert flag.status == FlagStatus.RESOLVED
    # A new hold/round supersedes the old row decision, including after offline release.
    svc.query_line(db, actor, second.id, "New supporting evidence needs clarification", flag.id)
    svc.accept_line(db, actor, second.id, "Released this hold; full finding still under review")
    svc.query_line(db, actor, third.id, "Clarify the other row again", flag.id)
    _, token = providers.create_link(db, actor, flag.id, third.id, "Explain this row.")
    response = providers.respond(db, token, ProviderResponseType.EXPLAIN, "Explanation.", "Desk")
    p = providers.preview(db, actor, response.id)
    providers.decide(
        db,
        actor,
        response.id,
        ProviderDecisionType.ACCEPT,
        "Accepted this explanation only.",
        p["state_fingerprint"],
    )
    assert flag.status == FlagStatus.OPEN
    assert svc.get_buckets(db, case).consistent
    assert any("possible duplicate" in blocker for blocker in svc.approval_blockers(db, case))


def test_second_session_with_preloaded_state_cannot_duplicate_resolution(db, context):
    case, actor, flag, line = context
    _, _, response = proposal(db, context)
    # Two distinct ORM identity maps share the fixture's rollback-only test connection.
    # This exercises stale cached dependent objects; database locking is handled by the
    # service and uniqueness constraints. It is not a wall-clock concurrency load test.
    stale = Session(
        bind=db.get_bind(), join_transaction_mode="rollback_only", expire_on_commit=False
    )
    try:
        stale.get(ProviderResponse, response.id)
        stale.get(BillingFlag, flag.id)
        first = providers.preview(stale, actor, response.id)
        current = providers.preview(db, actor, response.id)
        providers.decide(
            db,
            actor,
            response.id,
            ProviderDecisionType.ACCEPT,
            "Accepted in the first session",
            current["state_fingerprint"],
        )
        count = len(svc.case_ledger(db, case.id))
        with pytest.raises(DomainError, match="changed|already"):
            providers.decide(
                stale,
                actor,
                response.id,
                ProviderDecisionType.ACCEPT,
                "Repeated from a stale second session",
                first["state_fingerprint"],
            )
        assert len(svc.case_ledger(db, case.id)) == count
        assert len(db.scalars(select(ProviderDecision)).all()) == 1
    finally:
        stale.close()


def test_old_mutators_cannot_bypass_provider_review(db, context):
    case, actor, flag, line = context
    _, _, response = proposal(db, context)
    with pytest.raises(DomainError):
        svc.accept_line(db, actor, line.id, "Try bypass")
    with pytest.raises(DomainError):
        svc.change_flag_status(db, actor, flag.id, "RESOLVED", "Try bypass")
    assert svc.get_buckets(db, case).queried == Decimal("2000")


def test_expired_and_revoked_links_are_uniform(db, context):
    case, actor, flag, line = context
    link, token = providers.create_link(db, actor, flag.id, line.id, "Please clarify.")
    # Scope is immutable, even expiry. Simulate the passage of time through the clock.
    from unittest.mock import patch

    with patch("app.services._now", return_value=datetime.now(UTC) + timedelta(days=2)):
        with pytest.raises(Forbidden, match="unavailable"):
            providers.portal(db, token)
    providers.revoke_link(db, actor, link.id, "Sent in error")
    for bad in (token, "x" * 43, "invalid"):
        with pytest.raises(Forbidden, match="unavailable"):
            providers.portal(db, bad)
    assert db.get(ProviderLink, link.id).token_sha256 != token


def test_stale_preview_is_rejected(db, context):
    case, actor, flag, line = context
    _, _, response = proposal(db, context)
    p = providers.preview(db, actor, response.id)
    svc.run_checks(db, actor, case.id)  # A non-ledger case event invalidates the decision.
    with pytest.raises(DomainError, match="changed"):
        providers.decide(
            db,
            actor,
            response.id,
            ProviderDecisionType.ACCEPT,
            "Accept stale view",
            p["state_fingerprint"],
        )


def test_reason_amount_and_replay_guards(db, context):
    case, actor, flag, line = context
    link, token = providers.create_link(db, actor, flag.id, line.id, "Please clarify.")
    for kind, reason, amount in [
        (ProviderResponseType.CORRECT, "Reason", None),
        (ProviderResponseType.EXPLAIN, "Reason", Decimal("1")),
        (ProviderResponseType.CORRECT, "Reason", Decimal("-1")),
        (ProviderResponseType.ACCEPT, " ", None),
    ]:
        with pytest.raises(ValidationFailed):
            providers.respond(db, token, kind, reason, "Desk", amount)
    providers.respond(db, token, ProviderResponseType.EXPLAIN, "Reason", "Desk")
    with pytest.raises(DomainError, match="already"):
        providers.respond(db, token, ProviderResponseType.EXPLAIN, "Again", "Desk")
    assert len(db.scalars(select(ProviderResponse)).all()) == 1


def test_decision_and_link_scope_immutable_in_orm_and_db(db, context):
    case, actor, flag, line = context
    link, _, response = proposal(db, context)
    p = providers.preview(db, actor, response.id)
    decision = providers.decide(
        db, actor, response.id, ProviderDecisionType.ACCEPT, "Accepted", p["state_fingerprint"]
    )
    with db.begin_nested() as nested:
        decision.note = "Changed"
        with pytest.raises(ImmutableRecordError):
            db.flush()
        nested.rollback()
    for sql in [
        "UPDATE provider_decisions SET note='Changed'",
        "DELETE FROM provider_decisions",
        "UPDATE provider_links SET question='Changed'",
        "DELETE FROM provider_links",
    ]:
        nested = db.begin_nested()
        with pytest.raises(DBAPIError, match="immutable|append-only"):
            db.execute(text(sql))
        nested.rollback()
    assert any(
        e.entry_type == LedgerEntryType.ADJUSTMENT_CREDIT for e in svc.case_ledger(db, case.id)
    )

"""Initialize demo identity, optionally adding the synthetic demonstration case.

    python -m app.seed
    python -m app.seed --with-example

The default creates only a payer identity. The example case is explicitly opt-in.

All data is synthetic and labelled SEEDED_SYNTHETIC / is_demo. The seed goes
through the same service functions as the API, so every amount produces ledger
entries and audit events.

Expected result: bill 25000.00 = payable_now 19000.00 + queried 2000.00 + already_paid 4000.00
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import services as svc
from app.models import CareCase, User
from app.states import DataSource, PaymentMethod, UserRole

DEMO_CASE_REF = "DEMO-001"
PROVIDER = "Synthetic City Hospital (Demo)"
SERVICE_DAY = date(2026, 11, 2)

DEMO_LINES = [
    svc.LineInput(
        1,
        "Room charges - general ward",
        Decimal("12000.00"),
        SERVICE_DAY,
        Decimal("2"),
        Decimal("6000.00"),
        source_page=1,
    ),
    svc.LineInput(
        2,
        "Physician consultation",
        Decimal("3000.00"),
        SERVICE_DAY,
        Decimal("1"),
        Decimal("3000.00"),
        source_page=1,
    ),
    svc.LineInput(
        3,
        "Complete blood count (CBC)",
        Decimal("2000.00"),
        SERVICE_DAY,
        Decimal("1"),
        Decimal("2000.00"),
        source_page=1,
    ),
    svc.LineInput(
        4,
        "Complete Blood Count (CBC)",
        Decimal("2000.00"),
        SERVICE_DAY,
        Decimal("1"),
        Decimal("2000.00"),
        source_page=1,
    ),
    svc.LineInput(
        5,
        "Pharmacy and consumables",
        Decimal("4500.00"),
        SERVICE_DAY,
        Decimal("1"),
        Decimal("4500.00"),
        source_page=2,
    ),
    svc.LineInput(
        6,
        "Nursing charges",
        Decimal("1500.00"),
        SERVICE_DAY,
        Decimal("1"),
        Decimal("1500.00"),
        source_page=2,
    ),
]


def _demo_user(db: Session, name: str, role: UserRole, email: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    return user or svc.create_user(db, name, role, email=email, is_demo=True)


def seed(db: Session) -> CareCase:
    existing = db.scalar(select(CareCase).where(CareCase.case_reference == DEMO_CASE_REF))
    if existing is not None:
        return existing

    payer = _demo_user(db, "Demo Payer (US relative)", UserRole.PAYER, "payer@demo.invalid")
    _demo_user(db, "Demo Relative (India)", UserRole.RELATIVE, "relative@demo.invalid")
    db.commit()
    actor = svc.Actor(user=payer, label=f"{payer.role}:{payer.display_name} [seed]")

    case = svc.create_case(
        db,
        actor,
        patient_alias="Patient A (synthetic)",
        currency="INR",
        case_reference=DEMO_CASE_REF,
        is_demo=True,
    )
    db.commit()

    bill = svc.add_bill(
        db,
        actor,
        case.id,
        svc.BillInput(
            provider_name=PROVIDER,
            currency="INR",
            bill_number="SCH-DEMO-0001",
            bill_date=date(2026, 11, 4),
            printed_total=Decimal("25000.00"),
            printed_advance_paid=Decimal("4000.00"),
            printed_balance_due=Decimal("21000.00"),
            source_document_ref="seed:synthetic-bill-001",
            lines=DEMO_LINES,
        ),
        source_type=DataSource.SEEDED_SYNTHETIC,
    )

    flags = svc.run_checks(db, actor, case.id)
    dup = next(f for f in flags if f.rule_id == "possible_exact_duplicate")
    by_number = {li.line_number: li for li in bill.line_items}
    repeat_id = by_number[4].id

    svc.query_line(
        db,
        actor,
        repeat_id,
        "Possible duplicate of line 3 (same date, test and amount). Asking provider to confirm.",
        flag_id=dup.id,
    )
    for n in (1, 2, 3, 5, 6):
        svc.accept_line(db, actor, by_number[n].id, "Reviewed by payer (seeded demo)")

    payment = svc.record_external_payment(
        db,
        actor,
        case.id,
        svc.PaymentInput(
            method=PaymentMethod.UPI,
            amount=Decimal("4000.00"),
            currency="INR",
            paid_on=date(2026, 11, 1),
            reference="DEMO-UPI-000000000001",
            payee_name="Synthetic City Hospital",
            bill_id=bill.id,
            source_document_ref="seed:synthetic-upi-receipt-001",
        ),
        source_type=DataSource.SEEDED_SYNTHETIC,
    )
    svc.reconcile_external_payment(db, actor, payment.id)
    return case


def seed_care_episode(db: Session) -> CareCase:
    """Create the Knee Replacement care episode from the Feature A specification."""
    ref = "EPISODE-KNEE-2026"
    existing = db.scalar(select(CareCase).where(CareCase.case_reference == ref))
    if existing is not None:
        return existing

    payer = _demo_user(db, "Demo Payer (US relative)", UserRole.PAYER, "payer@demo.invalid")
    actor = svc.Actor(user=payer, label=f"{payer.role}:{payer.display_name} [seed]")

    case = svc.create_case(
        db,
        actor,
        patient_alias="Father",
        currency="INR",
        case_reference=ref,
        episode_title="Knee Replacement — November 2026",
        clinical_context=(
            "Pre-admission assessment, bilateral knee investigations, "
            "total knee replacement surgery and inpatient stay."
        ),
        is_demo=True,
    )
    db.commit()

    # Document 1: Initial Consultation (Oct 22, 2026) — ₹1,000
    svc.add_bill(
        db,
        actor,
        case.id,
        svc.BillInput(
            provider_name="City Orthopedic & Specialty Hospital",
            currency="INR",
            bill_number="CONS-2026-101",
            bill_date=date(2026, 10, 22),
            printed_total=Decimal("1000.00"),
            source_document_ref="seed:doc-consult-01",
            lines=[
                svc.LineInput(
                    line_number=1,
                    description_raw="Orthopedic Specialist Consultation",
                    line_total=Decimal("1000.00"),
                    service_date=date(2026, 10, 22),
                    quantity=Decimal("1"),
                    unit_price=Decimal("1000.00"),
                )
            ],
        ),
        source_type=DataSource.SEEDED_SYNTHETIC,
    )

    # Document 2: Diagnostics (Oct 22, 2026) — ₹4,000
    svc.add_bill(
        db,
        actor,
        case.id,
        svc.BillInput(
            provider_name="City Orthopedic & Specialty Hospital",
            currency="INR",
            bill_number="DIAG-2026-402",
            bill_date=date(2026, 10, 22),
            printed_total=Decimal("4000.00"),
            source_document_ref="seed:doc-diag-02",
            lines=[
                svc.LineInput(
                    line_number=1,
                    description_raw="Pre-operative Blood Panel & CBC",
                    line_total=Decimal("2000.00"),
                    service_date=date(2026, 10, 22),
                    quantity=Decimal("1"),
                    unit_price=Decimal("2000.00"),
                ),
                svc.LineInput(
                    line_number=2,
                    description_raw="Digital Knee X-Ray & MRI",
                    line_total=Decimal("2000.00"),
                    service_date=date(2026, 10, 22),
                    quantity=Decimal("1"),
                    unit_price=Decimal("2000.00"),
                ),
            ],
        ),
        source_type=DataSource.SEEDED_SYNTHETIC,
    )

    # Document 4: Inpatient / Surgery Comprehensive Bill (Oct 26, 2026) — ₹46,000
    # Includes Surgery ₹35,000, Pharmacy ₹6,000, Consultation ₹1,000, repeated Diagnostics ₹4,000
    final_bill = svc.add_bill(
        db,
        actor,
        case.id,
        svc.BillInput(
            provider_name="City Orthopedic & Specialty Hospital",
            currency="INR",
            bill_number="HOSP-FINAL-2026-900",
            bill_date=date(2026, 10, 26),
            printed_total=Decimal("46000.00"),
            printed_advance_paid=Decimal("10000.00"),
            printed_balance_due=Decimal("36000.00"),
            source_document_ref="seed:doc-final-bill-04",
            lines=[
                svc.LineInput(
                    line_number=1,
                    description_raw="Knee Replacement Surgery Procedure & OR Package",
                    line_total=Decimal("35000.00"),
                    service_date=date(2026, 10, 26),
                    quantity=Decimal("1"),
                    unit_price=Decimal("35000.00"),
                ),
                svc.LineInput(
                    line_number=2,
                    description_raw="Post-op Pharmacy & Injectables",
                    line_total=Decimal("6000.00"),
                    service_date=date(2026, 10, 26),
                    quantity=Decimal("1"),
                    unit_price=Decimal("6000.00"),
                ),
                svc.LineInput(
                    line_number=3,
                    description_raw="Pre-operative Blood Panel & CBC",
                    line_total=Decimal("2000.00"),
                    service_date=date(2026, 10, 26),
                    quantity=Decimal("1"),
                    unit_price=Decimal("2000.00"),
                ),
                svc.LineInput(
                    line_number=4,
                    description_raw="Digital Knee X-Ray & MRI",
                    line_total=Decimal("2000.00"),
                    service_date=date(2026, 10, 26),
                    quantity=Decimal("1"),
                    unit_price=Decimal("2000.00"),
                ),
                svc.LineInput(
                    line_number=5,
                    description_raw="Inpatient Doctor Rounds Consultation",
                    line_total=Decimal("1000.00"),
                    service_date=date(2026, 10, 26),
                    quantity=Decimal("1"),
                    unit_price=Decimal("1000.00"),
                ),
            ],
        ),
        source_type=DataSource.SEEDED_SYNTHETIC,
    )

    # Document 3: Advance Payment Receipt (Oct 24, 2026) — ₹10,000
    payment = svc.record_external_payment(
        db,
        actor,
        case.id,
        svc.PaymentInput(
            method=PaymentMethod.UPI,
            amount=Decimal("10000.00"),
            currency="INR",
            bill_id=final_bill.id,
            paid_on=date(2026, 10, 24),
            reference="UPI-ADV-KNEE-2026-001",
            payee_name="City Orthopedic & Specialty Hospital",
            source_document_ref="seed:receipt-advance-03",
        ),
        source_type=DataSource.SEEDED_SYNTHETIC,
    )
    svc.reconcile_external_payment(db, actor, payment.id)

    # Run checks to detect discrepancies
    svc.run_checks(db, actor, case.id)
    db.commit()
    return case


def main() -> None:
    import argparse

    from app.db import SessionLocal

    parser = argparse.ArgumentParser(
        description="Initialize local demo identity; samples are opt-in."
    )
    parser.add_argument(
        "--with-example", action="store_true", help="Also create the synthetic INR example"
    )
    parser.add_argument(
        "--with-episode", action="store_true", help="Create the Knee Replacement care episode"
    )
    args = parser.parse_args()
    with SessionLocal() as db:
        if not args.with_example and not args.with_episode:
            _demo_user(db, "Demo Payer (US relative)", UserRole.PAYER, "payer@demo.invalid")
            db.commit()
            print("Demo identity initialized. No example cases created.")
            return
        if args.with_episode:
            case = seed_care_episode(db)
            b = svc.get_buckets(db, case)
            print(
                f"Care Episode: {case.episode_title} [{case.case_reference}] ({case.currency}):\n"
                f"  bill: {b.bill_total} = payable: {b.payable_now} "
                f"+ queried: {b.queried} + already_paid: {b.already_paid}"
            )
        if args.with_example:
            case = seed(db)
            b = svc.get_buckets(db, case)
            print(
                f"{case.case_reference} [{case.status}] {b.currency}: "
                f"bill {b.bill_total} = payable_now {b.payable_now} + queried {b.queried} "
                f"+ already_paid {b.already_paid}; consistent={b.consistent}"
            )


if __name__ == "__main__":
    main()

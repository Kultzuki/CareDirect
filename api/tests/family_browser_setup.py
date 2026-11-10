"""Synthetic browser fixtures restricted to caredirect_test; no capability links are printed."""

import json
import os
from pathlib import Path

from app.config import Settings

os.environ["DATABASE_URL"] = Settings().test_database_url
os.environ["DEEPSEEK_API_KEY"] = " "
os.environ["GEMINI_API_KEY"] = " "

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import family
from app import services as svc
from app.db import engine
from app.models import User
from app.states import UserRole

if __name__ == "__main__":
    if not os.environ["DATABASE_URL"].endswith("/caredirect_test"):
        raise RuntimeError("Synthetic browser setup requires caredirect_test")
    with Session(engine, expire_on_commit=False) as db:

        def identity(name, email, role=UserRole.RELATIVE):
            return db.scalar(select(User).where(User.email == email)) or svc.create_user(
                db, name, role, email=email, is_demo=True
            )

        owner = identity("Demo Payer (US relative)", "payer@demo.invalid", UserRole.PAYER)
        actor = svc.Actor(owner, owner.display_name)
        case = svc.create_case(
            db,
            actor,
            patient_alias="Synthetic parents",
            currency="INR",
            episode_title="Family E browser check",
            is_demo=True,
        )
        db.commit()
        siblings = []
        for name, email, role, review, approve in (
            ("Daughter in USA", "daughter@family.invalid", "PAYER", True, False),
            ("Son in UK", "uk@family.invalid", "PAYER", False, True),
            ("Son in India", "india@family.invalid", "PAYER", False, False),
            ("Parent (patient)", "parent@family.invalid", "PATIENT", False, False),
        ):
            user = identity(name, email)
            invitation = family.invite(
                db,
                actor,
                case.id,
                family.InviteRequest(
                    recipient_email=email, role=role, can_review=review, can_approve=approve
                ),
            )
            family.accept_invitation(db, svc.Actor(user, name), invitation["token"])
            siblings.append(user)
        for user, amount in zip(siblings[:3], ("30000", "20000", "10000"), strict=True):
            family.contribute(
                db,
                actor,
                case.id,
                family.ContributionRequest(
                    user_id=user.id,
                    amount=amount,
                    currency="INR",
                    contributed_on=svc._now().date(),
                    request_id=uuid4().hex,
                    note="Synthetic browser contribution record",
                ),
            )
        bill = svc.add_bill(
            db,
            actor,
            case.id,
            svc.BillInput(
                provider_name="Synthetic hospital",
                currency="INR",
                printed_total=Decimal("60000"),
                lines=[svc.LineInput(1, "Reviewed hospital services", Decimal("60000"))],
            ),
        )
        svc.accept_line(db, actor, bill.line_items[0].id)
        _, fingerprint = family.line_basis(db, bill.line_items[0])
        family.allocate(
            db,
            actor,
            case.id,
            family.AllocationRequest(
                line_item_id=bill.line_items[0].id,
                source_fingerprint=fingerprint,
                shares=[
                    family.Share(user_id=user.id, amount=amount)
                    for user, amount in zip(siblings[:3], ("30000", "20000", "10000"), strict=True)
                ],
                request_id=uuid4().hex,
                note="Synthetic family split",
            ),
        )
        output = Path(__file__).resolve().parents[2] / "output/playwright/family"
        output.mkdir(parents=True, exist_ok=True)
        metadata = dict(
            case_id=str(case.id),
            owner_id=str(owner.id),
            actors={user.display_name: str(user.id) for user in siblings},
        )
        (output / "fixture.json").write_text(json.dumps(metadata), encoding="utf-8")
        print(json.dumps(metadata))

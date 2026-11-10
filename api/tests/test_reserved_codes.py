"""Untrusted service codes cannot masquerade as synthesized accounting lines."""

import pytest
from pydantic import ValidationError

from app.extraction.schema import LineItemV1
from app.schemas import LineCreate
from tests.test_extraction_schema import fld, line


@pytest.mark.parametrize("code", ["CAREDIRECT_TAX", "caredirect_tax", "  CareDirect_Tax  "])
def test_manual_line_cannot_claim_reserved_tax_code(code):
    with pytest.raises(ValidationError, match="reserved internal"):
        LineCreate.model_validate(
            {
                "line_number": 1,
                "description_raw": "Synthetic charge",
                "line_total": "100.00",
                "code": code,
            }
        )


@pytest.mark.parametrize("code", ["CAREDIRECT_TAX", "caredirect_tax", "  CareDirect_Tax  "])
def test_model_line_cannot_claim_reserved_tax_code(code):
    with pytest.raises(ValidationError, match="reserved internal"):
        LineItemV1.model_validate(line(code=fld(code)))


@pytest.mark.parametrize("code", [None, "SYNTHETIC-CONSULTATION"])
def test_ordinary_service_codes_remain_available(code):
    manual = LineCreate.model_validate(
        {
            "line_number": 1,
            "description_raw": "Synthetic charge",
            "line_total": "100.00",
            "code": code,
        }
    )
    extracted = LineItemV1.model_validate(line(code=fld(code)))
    assert manual.code == extracted.code.value == code


@pytest.mark.parametrize("code", ["CAREDIRECT_TAX", "caredirect_tax", "  CareDirect_Tax  "])
def test_human_revision_cannot_claim_reserved_tax_code(client, db, headers, actor, code):
    from app import services as svc
    from tests.test_extraction_flow import extract, ingest, revise

    case = svc.create_case(
        db, actor, patient_alias="Synthetic reserved code review", currency="INR"
    )
    db.commit()
    view = extract(client, headers, ingest(client, headers, case, "clean_bill"))
    result = revise(
        client,
        headers,
        view["id"],
        corrections=[
            {
                "path": "line_items.0.code",
                "value": code,
            }
        ],
    )
    assert result.status_code == 422
    assert "reserved internal" in result.json()["message"]
    assert svc.case_ledger(db, case.id) == []

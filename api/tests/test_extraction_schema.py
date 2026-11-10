"""The versioned extraction schema: AI output is untrusted and must fail closed."""

import copy
import uuid
from decimal import Decimal

import pytest

from app.extraction.schema import (
    LOW_CONFIDENCE_THRESHOLD,
    SCHEMA_VERSION,
    ExtractionRejected,
    ExtractionV1,
    build_source,
    iter_fields,
    parse_extraction,
    parse_field_value,
    review_required,
)

DOC = uuid.UUID("11111111-1111-4111-8111-111111111111")
NULL = {"value": None, "confidence": None, "source": None}


def src(page=1, snippet="Total 1500.00", doc=DOC, **extra):
    return {"document_id": str(doc), "page": page, "snippet": snippet, "bbox": None, **extra}


def fld(value, confidence="0.950", **source):
    return {"value": value, "confidence": confidence, "source": src(**source)}


def line(number=1, total="1500.00", **overrides):
    data = {
        "line_number": number,
        "description": fld("Consultation"),
        "code": fld("CONS-01"),
        "service_date": fld("2026-10-30"),
        "quantity": fld("1"),
        "unit_price": fld("1500.00"),
        "line_total": fld(total),
    }
    data.update(overrides)
    return data


def payload(**overrides):
    data = {
        "schema_version": SCHEMA_VERSION,
        "document_id": str(DOC),
        "document_type": "BILL",
        "provider_name": fld("Synthetic City Hospital (Demo)"),
        "provider_identifier": fld("SYN-REG-0001"),
        "patient_reference": fld("PT-SYN-001"),
        "invoice_number": fld("INV-SYN-1001"),
        "invoice_date": fld("2026-11-01"),
        "currency": fld("INR"),
        "line_items": [line()],
        "subtotal": fld("1500.00"),
        "tax_total": fld("0.00"),
        "total": fld("1500.00"),
        "advance_paid": NULL,
        "receipt": None,
    }
    data.update(overrides)
    return data


def all_null_payload():
    keys = (
        "provider_name",
        "provider_identifier",
        "patient_reference",
        "invoice_number",
        "invoice_date",
        "currency",
        "subtotal",
        "tax_total",
        "total",
        "advance_paid",
    )
    return payload(line_items=[], **{k: dict(NULL) for k in keys})


def parse(raw, page_count=2):
    return parse_extraction(raw, document_id=DOC, page_count=page_count)


def rejected(raw, page_count=2):
    with pytest.raises(ExtractionRejected) as caught:
        parse(raw, page_count)
    return caught.value


# ---------------------------------------------------------------- valid output


def test_valid_payload_parses_and_normalises_values():
    ex = parse(payload())
    assert ex.document_id == DOC
    assert ex.line_items[0].quantity.value == Decimal("1.000")
    assert ex.line_items[0].line_total.value == Decimal("1500.00")
    assert ex.advance_paid.value is None
    dumped = ex.model_dump(mode="json")
    assert dumped["line_items"][0]["quantity"]["value"] == "1.000"
    assert dumped["line_items"][0]["line_total"]["value"] == "1500.00"
    assert dumped["provider_name"]["confidence"] == "0.950"
    assert dumped["document_id"] == str(DOC)


def test_stored_payload_round_trips():
    ex = parse(payload(line_items=[line(1), line(2, "99.50", unit_price=fld("99.50"))]))
    again = ExtractionV1.model_validate(
        ex.model_dump(mode="json"), context={"document_id": DOC, "page_count": 2}
    )
    assert again == ex


def test_all_null_payload_with_no_lines_parses():
    ex = parse(all_null_payload())
    assert ex.line_items == []
    assert review_required(ex, set()) == []
    assert all(info.field.value is None for info in iter_fields(ex))


def test_receipt_payload_parses():
    receipt = {
        "amount": fld("4500.00"),
        "paid_on": fld("2026-10-29"),
        "transaction_reference": fld("SYNUPI0000123"),
        "payee_name": fld("Synthetic Diagnostics Lab"),
        "payment_method": fld("UPI"),
    }
    ex = parse(payload(document_type="RECEIPT", receipt=receipt))
    assert ex.receipt.payment_method.value == "UPI"


def test_bounding_box_source_without_snippet_parses():
    box = {"x0": "0.100", "y0": "0.200", "x1": "0.300", "y1": "0.250"}
    ex = parse(
        payload(
            total={"value": "1500.00", "confidence": "0.9", "source": src(snippet=None, bbox=box)}
        )
    )
    assert ex.total.source.bbox.x1 == Decimal("0.300")


# ---------------------------------------------------------------- unknown keys


def test_unknown_top_level_key_rejected():
    err = rejected({**payload(), "extra": 1})
    assert {"loc": ["extra"], "type": "extra_forbidden"} in err.errors


def test_patient_name_is_rejected():
    err = rejected({**payload(), "patient_name": fld("Someone")})
    assert {"loc": ["patient_name"], "type": "extra_forbidden"} in err.errors


def test_unknown_key_in_a_line_rejected():
    err = rejected(payload(line_items=[{**line(), "discount": fld("1.00")}]))
    assert {"loc": ["line_items", 0, "discount"], "type": "extra_forbidden"} in err.errors


def test_unknown_key_in_a_field_rejected():
    bad = {**fld("INV-1"), "note": "x"}
    err = rejected(payload(invoice_number=bad))
    assert {"loc": ["invoice_number", "note"], "type": "extra_forbidden"} in err.errors


def test_unknown_key_in_a_source_rejected():
    bad = {"value": "INV-1", "confidence": "0.95", "source": src(url="http://x")}
    err = rejected(payload(invoice_number=bad))
    assert any(e["loc"][-1] == "url" and e["type"] == "extra_forbidden" for e in err.errors)


def test_missing_field_is_rejected_not_defaulted():
    raw = payload()
    del raw["invoice_number"]
    assert {"loc": ["invoice_number"], "type": "missing"} in rejected(raw).errors


def test_wrong_schema_version_rejected():
    assert rejected(payload(schema_version="caredirect.extraction.v0")).errors


@pytest.mark.parametrize("raw", [[], "text", None, 5, [payload()]])
def test_non_object_output_rejected(raw):
    assert rejected(raw).errors == [{"loc": [], "type": "not_an_object"}]


# ---------------------------------------------------------------- numbers


@pytest.mark.parametrize("bad", [1500.0, 1500, "12.345", "abc", True, ["1"]])
def test_bad_money_rejected(bad):
    assert rejected(payload(total=fld(bad))).errors


@pytest.mark.parametrize("bad", [0.95, 1, "1.5", "-0.1", "abc", "NaN", "Infinity", "0.9501", True])
def test_bad_confidence_rejected(bad):
    assert rejected(payload(total=fld("1500.00", confidence=bad))).errors


def test_confidence_is_normalised_to_three_places():
    ex = parse(payload(total=fld("1500.00", confidence="0.9")))
    assert ex.total.confidence == Decimal("0.900")
    assert ex.model_dump(mode="json")["total"]["confidence"] == "0.900"


@pytest.mark.parametrize("bad", ["0", "-1", 1.5, "1.0005"])
def test_bad_quantity_rejected(bad):
    assert rejected(payload(line_items=[line(quantity=fld(bad))])).errors


# ---------------------------------------------------------------- evidence rules


def test_value_without_a_source_rejected():
    assert rejected(payload(total={"value": "1.00", "confidence": "0.95", "source": None})).errors


def test_value_without_a_confidence_rejected():
    assert rejected(payload(total={"value": "1.00", "confidence": None, "source": src()})).errors


def test_source_with_neither_snippet_nor_box_rejected():
    bad = {"value": "1.00", "confidence": "0.95", "source": src(snippet=None)}
    assert rejected(payload(total=bad)).errors


@pytest.mark.parametrize(
    "box",
    [
        {"x0": "0.5", "y0": "0.1", "x1": "0.4", "y1": "0.2"},
        {"x0": "0.1", "y0": "0.1", "x1": "1.5", "y1": "0.2"},
        {"x0": 0.1, "y0": 0.1, "x1": 0.2, "y1": 0.2},
    ],
)
def test_bad_bounding_box_rejected(box):
    bad = {"value": "1.00", "confidence": "0.95", "source": src(snippet=None, bbox=box)}
    assert rejected(payload(total=bad)).errors


def test_source_page_beyond_the_document_rejected():
    assert rejected(payload(total=fld("1.00", page=3)), page_count=2).errors
    assert parse(payload(total=fld("1.00", page=2)), page_count=2)


@pytest.mark.parametrize("page", [0, -1, 1.0, "1", True])
def test_bad_source_page_rejected(page):
    assert rejected(payload(total=fld("1.00", page=page))).errors


def test_source_for_another_document_rejected():
    other = uuid.uuid4()
    assert rejected(payload(total=fld("1.00", doc=other))).errors


def test_top_level_document_id_mismatch_rejected():
    assert rejected(payload(document_id=str(uuid.uuid4()))).errors


# ---------------------------------------------------------------- other fields


@pytest.mark.parametrize(
    "bad", [20261102, 1_762_041_600, "2026-13-01", "02/11/2026", "2026-11-02T10:00:00"]
)
def test_bad_date_rejected(bad):
    assert rejected(payload(invoice_date=fld(bad))).errors


def test_duplicate_line_number_rejected():
    assert rejected(payload(line_items=[line(1), line(1)])).errors


@pytest.mark.parametrize("number", [0, 501, "1", 1.0, True])
def test_bad_line_number_rejected(number):
    assert rejected(payload(line_items=[line(number)])).errors


def test_too_many_lines_rejected():
    assert rejected(payload(line_items=[line(n) for n in range(1, 502)])).errors


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("invoice_number", "X" * 81),
        ("provider_identifier", "X" * 41),
        ("patient_reference", "X" * 41),
        ("provider_name", "X" * 201),
        ("currency", "inr"),
        ("currency", "INRX"),
        ("invoice_number", ""),
        ("invoice_number", 12345),
        ("invoice_number", "bad\x00value"),
    ],
)
def test_bad_text_field_rejected(name, value):
    assert rejected(payload(**{name: fld(value)})).errors


def test_text_at_the_column_limit_is_accepted():
    assert parse(payload(invoice_number=fld("X" * 80)))


def test_line_description_and_code_limits():
    assert rejected(payload(line_items=[line(description=fld("D" * 501))])).errors
    assert rejected(payload(line_items=[line(code=fld("C" * 41))])).errors


def test_unknown_document_type_or_payment_method_rejected():
    assert rejected(payload(document_type="PASSPORT")).errors
    receipt = {
        "amount": fld("1.00"),
        "paid_on": NULL,
        "transaction_reference": NULL,
        "payee_name": NULL,
        "payment_method": fld("BITCOIN"),
    }
    assert rejected(payload(receipt=receipt)).errors


def test_errors_carry_locations_and_types_only_never_input_values():
    secret = "SECRET-PATIENT-TEXT-12345"
    raw = payload(
        invoice_number=fld(secret * 10),
        total=fld(secret, confidence=secret),
        patient_name=secret,
    )
    err = rejected(raw)
    assert secret not in str(err.errors)
    assert secret not in str(err)
    assert all(set(e) == {"loc", "type"} for e in err.errors)


# ---------------------------------------------------------------- field walking and review


def test_iter_fields_order_labels_and_paths():
    ex = parse(payload(line_items=[line(1), line(2)]))
    infos = list(iter_fields(ex))
    paths = [i.path for i in infos]
    assert paths[:6] == [
        "provider_name",
        "provider_identifier",
        "patient_reference",
        "invoice_number",
        "invoice_date",
        "currency",
    ]
    assert paths[6:12] == [
        f"line_items.0.{n}"
        for n in ("description", "code", "service_date", "quantity", "unit_price", "line_total")
    ]
    assert paths[12] == "line_items.1.description"
    assert paths[-4:] == ["subtotal", "tax_total", "total", "advance_paid"]
    assert len(paths) == len(set(paths)) == 6 + 12 + 4

    by_path = {i.path: i for i in infos}
    total = by_path["line_items.0.line_total"]
    assert total.label == "Line 1 line total"
    assert (total.group, total.line_index, total.line_number, total.name, total.kind) == (
        "line_item",
        0,
        1,
        "line_total",
        "money",
    )
    assert by_path["line_items.1.unit_price"].label == "Line 2 unit price"
    assert by_path["advance_paid"].label == "Advance paid (as printed)"
    assert by_path["subtotal"].group == "totals"
    assert by_path["provider_identifier"].group == "document"


def test_receipt_fields_are_listed_only_when_a_receipt_exists():
    assert not any(i.path.startswith("receipt.") for i in iter_fields(parse(payload())))
    receipt = {
        "amount": fld("4500.00"),
        "paid_on": NULL,
        "transaction_reference": NULL,
        "payee_name": NULL,
        "payment_method": fld("UPI"),
    }
    infos = {i.path: i for i in iter_fields(parse(payload(receipt=receipt)))}
    assert infos["receipt.amount"].label == "Receipt amount"
    assert infos["receipt.payment_method"].kind == "payment_method"
    assert infos["receipt.amount"].group == "receipt"


def test_review_required_lists_low_confidence_values_and_drops_reviewed_ones():
    ex = parse(
        payload(
            provider_identifier=fld("SYN-REG-0001", confidence="0.700"),
            line_items=[line(1, total="1700.00", line_total=fld("1700.00", confidence="0.550"))],
            invoice_date=NULL,
            invoice_number=fld("INV-1", confidence="0.900"),
        )
    )
    assert LOW_CONFIDENCE_THRESHOLD == Decimal("0.900")
    assert review_required(ex, set()) == ["provider_identifier", "line_items.0.line_total"]
    assert review_required(ex, {"provider_identifier"}) == ["line_items.0.line_total"]
    assert review_required(ex, {"provider_identifier", "line_items.0.line_total"}) == []
    # A null value is never flagged by confidence; exactly 0.900 passes.
    assert "invoice_date" not in review_required(ex, set())
    assert "invoice_number" not in review_required(ex, set())


# ---------------------------------------------------------------- correction values


@pytest.mark.parametrize(
    ("kind", "max_len", "raw", "expected"),
    [
        ("money", None, "1200", "1200.00"),
        ("money", None, " 1200.5 ", "1200.50"),
        ("money", None, "-5", "-5.00"),
        ("quantity", None, "2", "2.000"),
        ("quantity", None, "2.5", "2.500"),
        ("date", None, "2026-11-02", "2026-11-02"),
        ("currency", None, "inr", "INR"),
        ("payment_method", None, "upi", "UPI"),
        ("text", 10, "  hello ", "hello"),
        ("text", 10, "", None),
        ("money", None, "   ", None),
        ("money", None, None, None),
    ],
)
def test_parse_field_value_normalises(kind, max_len, raw, expected):
    assert parse_field_value(kind, max_len, raw) == expected


@pytest.mark.parametrize(
    ("kind", "max_len", "raw"),
    [
        ("money", None, "12.345"),
        ("money", None, "1e3"),
        ("money", None, "1,000.00"),
        ("money", None, "abc"),
        ("money", None, "9999999999999.00"),
        ("quantity", None, "0"),
        ("quantity", None, "1.2345"),
        ("quantity", None, "-1"),
        ("date", None, "02/11/2026"),
        ("date", None, "2026-02-30"),
        ("currency", None, "RUPEE"),
        ("payment_method", None, "bitcoin"),
        ("text", 5, "toolong"),
        ("text", None, "bad\x00"),
    ],
)
def test_parse_field_value_rejects(kind, max_len, raw):
    with pytest.raises(ValueError):
        parse_field_value(kind, max_len, raw)


def test_build_source_checks_the_document_and_page():
    ok = build_source({"page": 2, "snippet": "x", "bbox": None}, document_id=DOC, page_count=2)
    assert ok.document_id == DOC and ok.page == 2
    with pytest.raises(ValueError):
        build_source({"page": 3, "snippet": "x", "bbox": None}, document_id=DOC, page_count=2)
    with pytest.raises(ValueError):
        build_source({"page": 1, "snippet": None, "bbox": None}, document_id=DOC, page_count=2)


def test_parse_does_not_mutate_its_input():
    raw = payload()
    snapshot = copy.deepcopy(raw)
    parse(raw)
    assert raw == snapshot

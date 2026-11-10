"""Regression test for the extraction-quality report. The numbers come from running the
fixtures through the pipeline, never from constants in the code."""

import pytest

from app.extraction.evaluate import HEADING, evaluate_all, evaluate_fixture, main
from app.extraction.synthetic import FIXTURES, FIXTURES_BY_NAME

EXACT = ["clean_bill", "duplicate_rows", "arithmetic_mismatch", "upi_receipt_mismatch"]


@pytest.mark.parametrize("name", EXACT)
def test_fixtures_that_the_recorded_output_matches_have_no_errors(name):
    result = evaluate_fixture(FIXTURES_BY_NAME[name])
    assert (result.wrong, result.missed, result.spurious) == ([], [], [])
    assert result.correct == result.fields
    assert result.lines_match
    assert result.flagged_for_review == []


def test_photographed_bill_has_one_wrong_value_and_one_missing_value():
    result = evaluate_fixture(FIXTURES_BY_NAME["photographed_bill"])
    assert result.wrong == ["line_items.0.line_total"]
    assert result.missed == ["invoice_date"]
    assert result.spurious == []
    assert result.correct == result.fields - 2
    assert result.lines_match


def test_the_confidence_gate_flags_the_wrong_value_but_cannot_flag_the_missing_one():
    result = evaluate_fixture(FIXTURES_BY_NAME["photographed_bill"])
    assert "line_items.0.line_total" in result.flagged_for_review
    assert result.errors_caught_by_review == ["line_items.0.line_total"]
    assert "invoice_date" not in result.flagged_for_review
    # The correct-but-unsure identifier is flagged too: review is cautious, not exact.
    assert result.flagged_for_review == ["provider_identifier", "line_items.0.line_total"]


def test_every_fixture_is_evaluated():
    assert [r.name for r in evaluate_all()] == [f.name for f in FIXTURES]


def test_report_states_what_it_measures_and_what_it_found(capsys):
    main()
    out = capsys.readouterr().out
    assert HEADING in out
    assert "not a real model's OCR quality" in out
    for fixture in FIXTURES:
        assert fixture.name in out
    results = evaluate_all()
    total = sum(r.fields for r in results)
    correct = sum(r.correct for r in results)
    assert f"overall: {correct}/{total} fields correct" in out
    assert "line_items.0.line_total" in out

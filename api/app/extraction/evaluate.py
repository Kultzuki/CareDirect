"""Extraction-quality report on the synthetic fixtures. SYNTHETIC DEMO DATA ONLY.

Runs each fixture through the same steps as the API, without a database: render the file,
validate the upload, run the adapter, validate the output against the schema, then compare
every field with the fixture's recorded truth.

With the mock adapter this measures the schema, validation and review-gate pipeline. It does
not measure how well any real model reads real documents; no such score exists yet.

    python -m app.extraction.evaluate
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from app.documents.validation import validate_upload
from app.extraction.adapter import MockExtractionAdapter
from app.extraction.schema import iter_fields, parse_extraction, review_required, value_to_str
from app.extraction.synthetic import FIXTURES, SyntheticFixture, render

HEADING = (
    "mock adapter replaying recorded synthetic outputs: measures the "
    "schema/validation/review pipeline, not a real model's OCR quality"
)


@dataclass(frozen=True)
class FixtureResult:
    name: str
    fields: int
    correct: int
    wrong: list[str]
    missed: list[str]  # truth has a value, the output is null
    spurious: list[str]  # truth is null, the output has a value
    expected_lines: int
    extracted_lines: int
    flagged_for_review: list[str]
    errors_caught_by_review: list[str]  # wrong values that the confidence gate flags

    @property
    def lines_match(self) -> bool:
        return self.expected_lines == self.extracted_lines


def _line_count(paths: list[str]) -> int:
    return len({p.split(".")[1] for p in paths if p.startswith("line_items.")})


def evaluate_fixture(fixture: SyntheticFixture) -> FixtureResult:
    content = render(fixture)
    checked = validate_upload(content, fixture.mime_type, max_bytes=len(content), max_pages=20)
    document_id = uuid.uuid4()
    raw = MockExtractionAdapter().extract(
        document_id=document_id,
        document_type=fixture.document_type,
        mime_type=fixture.mime_type,
        content=content,
        page_count=checked.page_count,
    )
    ex = parse_extraction(raw, document_id=document_id, page_count=checked.page_count)
    actual = {info.path: value_to_str(info.kind, info.field.value) for info in iter_fields(ex)}

    paths = list(dict.fromkeys([*fixture.truth, *actual]))
    wrong: list[str] = []
    missed: list[str] = []
    spurious: list[str] = []
    for path in paths:
        expected, got = fixture.truth.get(path), actual.get(path)
        if expected == got:
            continue
        if got is None:
            missed.append(path)
        elif expected is None:
            spurious.append(path)
        else:
            wrong.append(path)
    flagged = review_required(ex, set())
    return FixtureResult(
        name=fixture.name,
        fields=len(paths),
        correct=len(paths) - len(wrong) - len(missed) - len(spurious),
        wrong=wrong,
        missed=missed,
        spurious=spurious,
        expected_lines=_line_count(list(fixture.truth)),
        extracted_lines=len(ex.line_items),
        flagged_for_review=flagged,
        errors_caught_by_review=[p for p in wrong if p in flagged],
    )


def evaluate_all() -> list[FixtureResult]:
    return [evaluate_fixture(f) for f in FIXTURES]


def _percent(correct: int, total: int) -> str:
    return f"{Decimal(correct * 100) / Decimal(total):.1f}%"


def main() -> None:
    results = evaluate_all()
    print(HEADING)
    print()
    columns = ("fixture", "fields", "correct", "wrong", "missed", "spurious", "lines")
    columns += ("flagged", "caught")
    print(f"{columns[0]:<22}" + "".join(f"{c:>9}" for c in columns[1:]))
    for r in results:
        cells = (r.fields, r.correct, len(r.wrong), len(r.missed), len(r.spurious))
        cells += (f"{r.extracted_lines}/{r.expected_lines}", len(r.flagged_for_review))
        cells += (len(r.errors_caught_by_review),)
        print(f"{r.name:<22}" + "".join(f"{c!s:>9}" for c in cells))
        for label, paths in (
            ("wrong", r.wrong),
            ("missed", r.missed),
            ("spurious", r.spurious),
            ("flagged for review", r.flagged_for_review),
        ):
            if paths:
                print(f"    {label}: {', '.join(paths)}")
    fields = sum(r.fields for r in results)
    correct = sum(r.correct for r in results)
    wrong = sum(len(r.wrong) for r in results)
    caught = sum(len(r.errors_caught_by_review) for r in results)
    print()
    print(f"overall: {correct}/{fields} fields correct ({_percent(correct, fields)})")
    print(f"wrong values: {wrong}, of which flagged for review by confidence: {caught}")
    print("a missing (null) value cannot be flagged by confidence")


if __name__ == "__main__":
    main()

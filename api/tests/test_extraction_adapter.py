"""Synthetic fixtures, recorded mock outputs and the mock adapter. No network, no real data."""

import re
import uuid
from pathlib import Path

import pytest

from app.config import Settings
from app.documents.validation import validate_upload
from app.errors import DomainError
from app.extraction import adapter as adapter_module
from app.extraction.adapter import (
    ExtractionUnavailable,
    MockExtractionAdapter,
    get_adapter,
    get_extraction_adapter,
)
from app.extraction.mock_outputs import MOCK_OUTPUTS
from app.extraction.schema import iter_fields, parse_extraction
from app.extraction.synthetic import FIXTURES, FIXTURES_BY_NAME, main, render

NAMES = [f.name for f in FIXTURES]
LIMITS = {"max_bytes": 20 * 1024 * 1024, "max_pages": 20}


def replay(fixture, document_id=None, **kw):
    content = kw.pop("content", None) or render(fixture)
    return MockExtractionAdapter().extract(
        document_id=document_id or uuid.uuid4(),
        document_type=fixture.document_type,
        mime_type=fixture.mime_type,
        content=content,
        page_count=1,
    )


def test_there_are_exactly_the_five_required_fixtures():
    assert NAMES == [
        "clean_bill",
        "photographed_bill",
        "duplicate_rows",
        "arithmetic_mismatch",
        "upi_receipt_mismatch",
    ]
    assert set(MOCK_OUTPUTS) == set(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_fixture_renders_and_passes_upload_validation(name):
    fixture = FIXTURES_BY_NAME[name]
    content = render(fixture)
    result = validate_upload(content, fixture.mime_type, **LIMITS)
    expected_pages = {"clean_bill": 2, "duplicate_rows": 1, "arithmetic_mismatch": 1}.get(name, 1)
    assert result.page_count == expected_pages
    assert len(fixture.pages) == expected_pages
    assert f"CAREDIRECT-SYNTHETIC-FIXTURE:{name}".encode() in content


@pytest.mark.parametrize("name", NAMES)
def test_rendering_is_deterministic(name):
    fixture = FIXTURES_BY_NAME[name]
    assert render(fixture) == render(fixture)


def test_pdf_fixtures_say_they_are_synthetic():
    from io import BytesIO

    from pypdf import PdfReader

    fixture = FIXTURES_BY_NAME["clean_bill"]
    text = " ".join(p.extract_text() for p in PdfReader(BytesIO(render(fixture))).pages)
    assert "SYNTHETIC DEMO DOCUMENT - NOT A REAL BILL" in text
    assert "INV-SYN-1001" in text


@pytest.mark.parametrize("name", NAMES)
def test_mock_output_passes_the_schema_for_its_own_document(name):
    fixture = FIXTURES_BY_NAME[name]
    pages = validate_upload(render(fixture), fixture.mime_type, **LIMITS).page_count
    document_id = uuid.uuid4()
    raw = replay(fixture, document_id)
    ex = parse_extraction(raw, document_id=document_id, page_count=pages)
    assert ex.document_id == document_id
    assert ex.document_type == fixture.document_type
    assert "{document_id}" not in str(raw)


@pytest.mark.parametrize("name", NAMES)
def test_truth_lists_exactly_the_schema_paths(name):
    fixture = FIXTURES_BY_NAME[name]
    document_id = uuid.uuid4()
    pages = validate_upload(render(fixture), fixture.mime_type, **LIMITS).page_count
    ex = parse_extraction(replay(fixture, document_id), document_id=document_id, page_count=pages)
    assert set(fixture.truth) == {info.path for info in iter_fields(ex)}


def test_replay_never_modifies_the_recorded_output():
    fixture = FIXTURES_BY_NAME["clean_bill"]
    before = repr(MOCK_OUTPUTS["clean_bill"])
    first_id, second_id = uuid.uuid4(), uuid.uuid4()
    first = replay(fixture, first_id)
    second = replay(fixture, second_id)
    assert first["document_id"] == str(first_id) and second["document_id"] == str(second_id)
    first["provider_name"]["value"] = "changed"
    assert repr(MOCK_OUTPUTS["clean_bill"]) == before
    assert replay(fixture)["provider_name"]["value"] != "changed"


def test_unknown_bytes_have_no_recorded_output():
    fixture = FIXTURES_BY_NAME["clean_bill"]
    with pytest.raises(ExtractionUnavailable, match="no recorded output"):
        replay(fixture, content=b"%PDF-1.4\nnot one of ours")


def test_unknown_marker_name_has_no_recorded_output():
    fixture = FIXTURES_BY_NAME["clean_bill"]
    content = render(fixture).replace(b"FIXTURE:clean_bill", b"FIXTURE:made_up_one")
    with pytest.raises(ExtractionUnavailable, match="no recorded output"):
        replay(fixture, content=content)


def test_only_the_mock_provider_is_enabled():
    assert isinstance(get_adapter("mock"), MockExtractionAdapter)
    with pytest.raises(DomainError, match="not enabled"):
        get_adapter("openai")
    with pytest.raises(DomainError, match="not enabled"):
        get_adapter("")


def test_auto_provider_without_key_uses_mock(monkeypatch):
    settings = Settings(_env_file=None, gemini_api_key="", document_ai_provider="auto")
    assert settings.document_ai_provider == "auto"
    monkeypatch.setattr(adapter_module, "get_settings", lambda: settings)
    assert isinstance(get_extraction_adapter(), MockExtractionAdapter)


def test_configured_real_provider_is_refused(monkeypatch):
    monkeypatch.setattr(
        adapter_module, "get_settings", lambda: Settings(document_ai_provider="anthropic")
    )
    with pytest.raises(DomainError, match="not enabled"):
        get_extraction_adapter()


def test_settings_have_no_document_ai_credentials():
    ai_settings = {n for n in Settings.model_fields if n.startswith("document_ai")}
    assert ai_settings == {"document_ai_provider", "document_ai_model"}


def test_adapter_module_has_no_network_client():
    source = Path(adapter_module.__file__).read_text(encoding="utf-8")
    imports = re.findall(r"^\s*(?:import|from)\s+([\w.]+)", source, flags=re.MULTILINE)
    banned = ("httpx", "requests", "urllib", "aiohttp", "socket", "http", "openai", "anthropic")
    assert not [m for m in imports if m.split(".")[0] in banned]


def test_command_line_writes_all_five_files(tmp_path, capsys):
    main(["--out", str(tmp_path / "fixtures")])
    written = sorted(p.name for p in (tmp_path / "fixtures").iterdir())
    assert written == sorted(f.filename for f in FIXTURES)
    assert capsys.readouterr().out.split() == [f.filename for f in FIXTURES]
    for fixture in FIXTURES:
        assert (tmp_path / "fixtures" / fixture.filename).read_bytes() == render(fixture)

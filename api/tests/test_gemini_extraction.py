"""Gemini extraction contract and durable local budgets. All model requests are mocked."""

import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from app.config import Settings
from app.extraction.adapter import ExtractionUnavailable, MockExtractionAdapter, get_adapter
from app.extraction.gemini import GeminiExtractionAdapter
from app.extraction.quota import GeminiQuota
from app.extraction.schema import ExtractionRejected, iter_fields, parse_extraction
from app.extraction.service import _resolve


@pytest.fixture
def adapter(tmp_path, monkeypatch):
    from app.extraction import gemini

    settings = Settings(
        _env_file=None,
        gemini_api_key="synthetic-key",
        storage_dir=str(tmp_path),
        gemini_quota_file=str(tmp_path / "quota.sqlite3"),
    )
    monkeypatch.setattr(gemini, "get_settings", lambda: settings)
    return GeminiExtractionAdapter()


def request(adapter, content=b"CAREDIRECT-SYNTHETIC-FIXTURE:clean_bill"):
    return dict(
        document_id=uuid4(),
        document_type="BILL",
        mime_type="application/pdf",
        content=content,
        page_count=2,
    )


def fake_responses(kwargs):
    raw = MockExtractionAdapter().extract(**kwargs)
    counted, generated = MagicMock(), MagicMock()
    counted.json.return_value = {"totalTokens": 100}
    generated.json.return_value = {
        "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(raw)}]}}]
    }
    return counted, generated


def test_pdf_extraction_uses_key_header_and_forces_human_review(adapter):
    kwargs = request(adapter)
    counted, generated = fake_responses(kwargs)
    with patch("httpx.Client.post", side_effect=[counted, generated]) as post:
        result = adapter.extract(**kwargs)
    parsed = parse_extraction(result, document_id=kwargs["document_id"], page_count=2)
    assert all(
        field.needs_review
        for field in _resolve(parsed, [], require_review=True)
        if field.value is not None
    )
    assert any(
        field.field.confidence > 0.900
        for field in iter_fields(parsed)
        if field.field.value is not None
    )
    assert post.call_count == 2
    assert ":countTokens" in post.call_args_list[0].args[0]
    assert post.call_args.args[0].endswith(":generateContent")
    assert "?key=" not in post.call_args.args[0]
    assert post.call_args.kwargs["headers"]["x-goog-api-key"] == "synthetic-key"
    assert (
        post.call_args.kwargs["json"]["contents"][0]["parts"][0]["inlineData"]["mimeType"]
        == "application/pdf"
    )


@pytest.mark.parametrize("mime", ["image/jpeg", "image/png"])
def test_image_bytes_are_sent_inline(adapter, mime):
    kwargs = request(adapter)
    kwargs["mime_type"] = mime
    with patch("httpx.Client.post", side_effect=fake_responses(kwargs)) as post:
        adapter.extract(**kwargs)
    assert (
        post.call_args.kwargs["json"]["contents"][0]["parts"][0]["inlineData"]["mimeType"] == mime
    )


def test_incomplete_or_invalid_model_output_is_rejected_without_retry(adapter):
    kwargs = request(adapter)
    counted, generated = fake_responses(kwargs)
    generated.json.return_value["candidates"][0]["finishReason"] = "MAX_TOKENS"
    with patch("httpx.Client.post", side_effect=[counted, generated]) as post:
        with pytest.raises(ExtractionUnavailable, match="incomplete"):
            adapter.extract(**kwargs)
        assert post.call_count == 2


def test_wrong_document_reference_is_rejected(adapter):
    kwargs = request(adapter)
    wrong = dict(kwargs, document_id=uuid4())
    counted, generated = fake_responses(wrong)
    with patch("httpx.Client.post", side_effect=[counted, generated]):
        with pytest.raises(ExtractionRejected):
            adapter.extract(**kwargs)


def test_token_limit_prevents_generation(adapter):
    counted = MagicMock()
    counted.json.return_value = {"totalTokens": 250001}
    with patch("httpx.Client.post", return_value=counted) as post:
        with pytest.raises(ExtractionUnavailable, match="input-token"):
            adapter.extract(**request(adapter))
        assert post.call_count == 1


def test_quota_error_is_safe_and_does_not_retry(adapter):
    response = httpx.Response(429, request=httpx.Request("POST", "https://example.invalid"))
    with patch(
        "httpx.Client.post",
        side_effect=httpx.HTTPStatusError(
            "secret response contents",
            request=response.request,
            response=response,
        ),
    ) as post:
        with pytest.raises(ExtractionUnavailable, match="quota exceeded") as error:
            adapter.extract(**request(adapter))
        assert "secret" not in str(error.value)
        assert post.call_count == 1


def test_daily_and_minute_limits_survive_new_instances(tmp_path):
    path = tmp_path / "quota.sqlite3"
    for i in range(20):
        GeminiQuota(path, "key").reserve(100, now=100000 + i * 61)
    with pytest.raises(ExtractionUnavailable, match="daily"):
        GeminiQuota(path, "key").reserve(now=103000)
    GeminiQuota(path, "key").reserve(now=200000)
    quota = GeminiQuota(tmp_path / "tokens.sqlite3", "key")
    quota.reserve(200000, now=100)
    with pytest.raises(ExtractionUnavailable, match="minute"):
        quota.reserve(60000, now=101)
    quota.reserve(60000, now=161)


def test_concurrent_reservations_cannot_exceed_rpm(tmp_path):
    def reserve(_):
        try:
            GeminiQuota(tmp_path / "concurrent.sqlite3", "key").reserve(now=100)
            return True
        except ExtractionUnavailable:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(8))) == 5


def test_gemini_can_be_selected_explicitly():
    assert isinstance(get_adapter("gemini"), GeminiExtractionAdapter)


def test_preflight_is_not_dispatched_when_pair_cannot_fit(tmp_path):
    quota = GeminiQuota(tmp_path / "pair.sqlite3", "key")
    for _ in range(4):
        quota.reserve(now=100)
    with pytest.raises(ExtractionUnavailable, match="minute"):
        quota.reserve(now=100, required_calls=2)

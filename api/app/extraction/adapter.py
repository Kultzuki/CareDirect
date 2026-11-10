"""Document extraction providers. Network providers are loaded only when selected."""

from __future__ import annotations

import re
import uuid
from typing import Any, Protocol

from app.config import get_settings
from app.errors import DomainError
from app.extraction.mock_outputs import DOCUMENT_ID, MOCK_OUTPUTS

_MARKER_RE = re.compile(rb"CAREDIRECT-SYNTHETIC-FIXTURE:([a-z_]{1,40})")


class ExtractionUnavailable(Exception):
    """The adapter has no output for this document. Nothing is invented."""


class ExtractionAdapter(Protocol):
    provider: str
    model: str
    prompt_version: str

    def extract(
        self,
        *,
        document_id: uuid.UUID,
        document_type: str,
        mime_type: str,
        content: bytes,
        page_count: int,
    ) -> object:
        """Return raw, untrusted extraction output for the document."""
        ...


def _fill(node: Any, document_id: str) -> Any:
    # Builds new containers, so the recorded output is never shared or modified.
    if isinstance(node, dict):
        return {key: _fill(value, document_id) for key, value in node.items()}
    if isinstance(node, list):
        return [_fill(value, document_id) for value in node]
    return document_id if node == DOCUMENT_ID else node


class MockExtractionAdapter:
    provider = "mock"
    model = "mock-replay-v1"
    prompt_version = "none"

    def extract(
        self,
        *,
        document_id: uuid.UUID,
        document_type: str,
        mime_type: str,
        content: bytes,
        page_count: int,
    ) -> object:
        match = _MARKER_RE.search(content)
        recorded = MOCK_OUTPUTS.get(match.group(1).decode("ascii")) if match else None
        if recorded is None and match and match.group(1).startswith(b"usd_"):
            from app.demo_samples import RECORDED_OUTPUTS

            recorded = RECORDED_OUTPUTS.get(match.group(1).decode("ascii"))
        if recorded is None:
            raise ExtractionUnavailable("mock provider has no recorded output for this document")
        return _fill(recorded, str(document_id))


def get_adapter(provider: str) -> ExtractionAdapter:
    settings = get_settings()
    if provider == "auto":
        provider = "gemini" if settings.gemini_api_key.strip() else "mock"
    if provider == "gemini":
        from app.extraction.gemini import GeminiExtractionAdapter

        return GeminiExtractionAdapter()
    if provider == "mock":
        return MockExtractionAdapter()
    raise DomainError(
        f"document AI provider '{provider}' is not enabled; choose auto, gemini or mock"
    )


def get_extraction_adapter() -> ExtractionAdapter:
    """FastAPI dependency. Tests override it with the mock adapter."""
    return get_adapter(get_settings().document_ai_provider)

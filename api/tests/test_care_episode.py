"""Tests for Feature A — Care Episode Intelligence."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from app.episode.deepseek import DeepSeekClient
from app.episode.service import get_care_episode
from app.seed import seed_care_episode


def test_care_episode_seeding_and_timeline(db: Session, payer):
    """Seed the Knee Replacement episode and verify chronological timeline and overlap analysis."""
    case = seed_care_episode(db)
    assert case.episode_title == "Knee Replacement — November 2026"
    assert case.patient_alias == "Father"
    assert len(case.bills) >= 3

    episode = get_care_episode(db, case.id)
    assert episode.episode_title == "Knee Replacement — November 2026"
    assert episode.patient_alias == "Father"
    assert len(episode.documents) >= 3
    assert len(episode.timeline) >= 5

    # Check chronological order of timeline
    dates = [t.event_date for t in episode.timeline if t.event_date != "Unknown date"]
    assert dates == sorted(dates)

    # Check that overlap detection found cross-document duplicates
    assert len(episode.overlaps) >= 1
    assert any(o.overlap_type == "PACKAGE_SCOPE" for o in episode.overlaps)

    # Check financial calculations
    assert Decimal(episode.total_billed) > 0
    assert Decimal(episode.overlap_deductions) == 0
    assert Decimal(episode.potential_overlap_amount) > 0
    assert episode.net_episode_total == episode.recorded_bill_total
    assert episode.already_paid == "10000.00"


def test_care_episode_api_endpoints(db: Session, client):
    """Test GET and POST /api/cases/{id}/episode."""
    case = seed_care_episode(db)
    headers = {"X-Demo-User-Id": str(case.payer_user_id)}

    # GET episode
    res = client.get(f"/api/cases/{case.id}/episode", headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["episode_title"] == "Knee Replacement — November 2026"
    assert data["patient_alias"] == "Father"
    assert "timeline" in data
    assert "overlaps" in data
    assert "ai_insights" in data

    # POST episode analyze
    res_post = client.post(f"/api/cases/{case.id}/episode/analyze", headers=headers)
    assert res_post.status_code == 200, res_post.text
    post_data = res_post.json()
    assert post_data["episode_title"] == "Knee Replacement — November 2026"


def test_deepseek_client_fallback_and_configured():
    """Verify DeepSeek client heuristic fallback and mock response parsing."""
    client_unconfigured = DeepSeekClient(api_key="")
    assert not client_unconfigured.is_configured
    result_heuristic = client_unconfigured.analyze_episode(
        case_data={"patient_alias": "Father", "episode_title": "Knee Replacement"},
        documents=[{"name": "Surgery", "amount": "35000.00"}],
        timeline_events=[{"title": "Surgery completed", "event_date": "2026-10-26"}],
        overlaps=[],
    )
    assert result_heuristic["provider"] == "deterministic-heuristic"
    assert result_heuristic["belongs_together"] is None
    assert "Knee Replacement" in result_heuristic["episode_title"]

    # Test configured with mock response
    client_configured = DeepSeekClient(api_key="test-key-mock")
    assert client_configured.is_configured

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"episode_title": "Knee Replacement Episode", '
                        '"clinical_summary": "Patient underwent total knee arthroplasty.", '
                        '"belongs_together": true, '
                        '"affinity_explanation": "All records match.", '
                        '"key_findings": ["Diagnostics overlapped with surgical package."], '
                        '"payer_recommendations": ["Clarify diagnostic inclusion."]}'
                    )
                }
            }
        ]
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.Client.post", return_value=mock_resp):
        res_ai = client_configured.analyze_episode(
            case_data={"patient_alias": "Father"},
            documents=[],
            timeline_events=[],
            overlaps=[],
        )
        assert res_ai["provider"] == "deepseek"
        assert res_ai["episode_title"] == "Knee Replacement Episode"
        assert res_ai["belongs_together"] is True

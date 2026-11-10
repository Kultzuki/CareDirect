"""Provider-tagged extraction reaches both A and B through the reviewed API pipeline."""

from app import services as svc
from app.extraction.adapter import MockExtractionAdapter, get_extraction_adapter
from app.extraction.synthetic import FIXTURES_BY_NAME, render
from app.main import app
from tests.test_documents_api import make_link, upload


def test_gemini_review_gate_feeds_episode_and_comparison(client, db, actor, headers):
    class SyntheticGemini(MockExtractionAdapter):
        provider = "gemini"

        def extract(self, **kwargs):
            raw = super().extract(**kwargs)
            raw["document_type"] = kwargs["document_type"]
            if raw["document_type"] == "ESTIMATE":
                raw["line_items"][0]["line_total"]["value"] = "1000.00"
                raw["total"]["value"] = raw["subtotal"]["value"] = "24500.00"
            return raw

    app.dependency_overrides[get_extraction_adapter] = SyntheticGemini
    case = svc.create_case(
        db,
        actor,
        patient_alias="Synthetic patient",
        currency="INR",
        episode_title="Connected synthetic episode",
    )
    db.commit()
    for kind in ("ESTIMATE", "BILL"):
        link = make_link(client, headers, case.id, (kind,))
        fixture = FIXTURES_BY_NAME["clean_bill"]
        uploaded = upload(
            client, link["token"], render(fixture) + kind.encode(), fixture.mime_type, kind
        )
        assert uploaded.status_code == 201
        doc_id = uploaded.json()["document_id"]
        response = client.post(f"/api/documents/{doc_id}/extract", headers=headers)
        assert response.status_code == 201, response.text
        view = response.json()
        assert view["provider"] == "gemini" and not view["is_mock"]
        assert all(f["needs_review"] for f in view["fields"] if f["value"] is not None)
        if kind == "BILL":
            assert (
                client.post(f"/api/extractions/{view['id']}/promote", headers=headers).status_code
                == 409
            )
        confirmed = client.post(
            f"/api/extractions/{view['id']}/revisions",
            headers=headers,
            json={
                "corrections": [],
                "confirmed_paths": [f["path"] for f in view["fields"] if f["needs_review"]],
                "reason": "Checked the synthetic source fields.",
            },
        )
        assert confirmed.status_code == 201, confirmed.text
        if kind == "BILL":
            assert (
                client.post(f"/api/extractions/{view['id']}/promote", headers=headers).status_code
                == 201
            )
        assert client.post(f"/api/documents/{doc_id}/extract", headers=headers).status_code == 409
    episode = client.get(f"/api/cases/{case.id}/episode", headers=headers).json()
    assert len(episode["documents"]) == 2 and episode["timeline"]
    comparison = client.get(f"/api/cases/{case.id}/estimate-comparison", headers=headers).json()
    assert comparison["difference"] == "500.00"
    assert comparison["extraction_providers"] == {"ESTIMATE": "gemini", "BILL": "gemini"}

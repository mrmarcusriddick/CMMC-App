from uuid import uuid4

import pytest
from sqlalchemy import select

from app import objectives
from app.catalog import seed_catalog
from app.database import get_session
from app.main import app
from app.models import (AssessmentRun, AssessmentObjective, Finding, EvidenceLog, ScreenshotEvidence,
                        FrameworkRelease, FrameworkPractice, FrameworkAssessmentObjective, ObjectiveReviewRevision)
from test_access_and_screenshots import client, sign_in


@pytest.fixture
def context(client, monkeypatch):
    from app import auth
    monkeypatch.setattr(objectives, "get_settings", auth.get_settings)
    session_generator = app.dependency_overrides[get_session]()
    db = next(session_generator)
    seed_catalog(db)
    objective = db.scalar(select(AssessmentObjective).order_by(AssessmentObjective.identifier))
    run = AssessmentRun(tenant_id="tenant-a")
    other = AssessmentRun(tenant_id="tenant-b")
    db.add_all([run, other]); db.flush()
    finding = Finding(run_id=run.id, objective_id=objective.id, status="MANUAL_REVIEW", detail="Original technical finding")
    db.add(finding); db.flush()
    evidence = EvidenceLog(finding_id=finding.id, source="Test discovery", payload={"test": True}, payload_hash="a" * 64, chain_hash="b" * 64)
    screenshot = ScreenshotEvidence(title="Supporting image", byte_size=4, image_data=b"test", sha256="c" * 64)
    db.add_all([evidence, screenshot]); db.commit()
    sign_in(client)
    yield {"client": client, "db": db, "run": run.id, "other": other.id, "identifier": objective.identifier,
           "base": f"/api/assessments/{run.id}/objectives/{objective.identifier}", "finding": finding.id,
           "evidence": evidence.id, "screenshot": screenshot.id}
    session_generator.close()


def payload(**kwargs):
    return {"expected_revision": 0, "owner": "Control owner", "status": "COMPLETE", "decision": "MET", "notes": "Reviewed the evidence.", **kwargs}


def test_catalog_and_missing_objective(context):
    c = context
    result = c["client"].get(f'/api/assessments/{c["run"]}/objectives').json()
    assert len(result["items"]) == 320
    assert all(item["review"]["revision"] == 0 for item in result["items"])
    assert c["client"].get(c["base"] + "-not-found").status_code == 404
    assert c["client"].get('/api/assessments/missing/objectives').status_code == 404


def test_review_revisions_do_not_change_findings_or_other_runs(context):
    c = context
    response = c["client"].put(c["base"] + '/review', json=payload(resources=[{"kind": "SCREENSHOT", "id": c["screenshot"]}]))
    assert response.status_code == 200, response.text
    assert response.json()["recordedBy"] == "reviewer"
    assert response.json()["resources"][0]["sha256"] == "c" * 64
    second = c["client"].put(c["base"] + '/review', json=payload(expected_revision=1, decision="NOT_MET", notes="A gap remains."))
    assert second.status_code == 200
    detail = c["client"].get(c["base"]).json()
    assert [item["revision"] for item in detail["history"]] == [2, 1]
    assert detail["history"][1]["decision"] == "MET"
    assert detail["history"][1]["resources"][0]["sha256"] == "c" * 64
    assert detail["findings"][0]["status"] == "MANUAL_REVIEW"
    other = c["client"].get(f'/api/assessments/{c["other"]}/objectives/{c["identifier"]}').json()
    assert other["review"]["revision"] == 0
    assert other["findings"] == []


def test_stale_review_and_invalid_completion_are_rejected(context):
    c = context
    assert c["client"].put(c["base"] + '/review', json=payload(notes="  ")).status_code == 422
    assert c["client"].put(c["base"] + '/review', json=payload()).status_code == 200
    assert c["client"].put(c["base"] + '/review', json=payload(notes="Stale overwrite")).status_code == 409
    assert len(c["client"].get(c["base"]).json()["history"]) == 1


def test_evidence_scope_and_resource_validation(context):
    c = context
    assert c["client"].put(c["base"] + '/review', json=payload(resources=[{"kind": "SCREENSHOT", "id": "missing"}])).status_code == 422
    other = f'/api/assessments/{c["other"]}/objectives/{c["identifier"]}'
    assert c["client"].put(other + '/review', json=payload(resources=[{"kind": "DISCOVERY", "id": c["evidence"]}])).status_code == 422
    assert c["client"].get(other + '/resources?kind=DISCOVERY').json()["items"] == []
    assert c["client"].get(c["base"] + '/resources?kind=SCREENSHOT&q=Supporting').json()["items"][0]["id"] == c["screenshot"]
    assert c["client"].put(c["base"] + '/review', json=payload(resources=[{"kind": "DISCOVERY", "id": c["evidence"]}])).status_code == 200


def test_poam_without_automated_finding_and_safe_retry(context):
    c = context
    base = f'/api/assessments/{c["other"]}/objectives/{c["identifier"]}'
    gap = {"request_key": str(uuid4()), "expected_revision": 1, "title": "Document the missing review", "owner": "Control owner"}
    assert c["client"].post(base + '/poam', json=gap).status_code == 409
    c["client"].put(base + '/review', json=payload(decision="NOT_MET"))
    created = c["client"].post(base + '/poam', json=gap)
    repeated = c["client"].post(base + '/poam', json=gap)
    assert created.status_code == 201, created.text
    assert repeated.json()["id"] == created.json()["id"]
    assert len(c["client"].get(base).json()["poam"]) == 1
    register = c["client"].get('/api/poam').json()["items"]
    assert register[0]["objective"] == c["identifier"]
    assert register[0]["findingId"] is None


def test_run_catalog_uses_its_original_release(context):
    c = context
    db = c["db"]
    release = FrameworkRelease(framework="CMMC", level=2, version="test-v1", source_url="https://example.test/guide", status="SOURCE_VALIDATED")
    db.add(release); db.flush()
    practice = FrameworkPractice(release_id=release.id, domain_code="AC", identifier="AC.TEST", title="Original practice", statement="Original requirement")
    db.add(practice); db.flush()
    objective = FrameworkAssessmentObjective(practice_id=practice.id, identifier="AC.TEST[a]", ordinal=1, statement="Original objective")
    run = AssessmentRun(tenant_id="tenant-a", framework_release_id=release.id)
    db.add_all([objective, run]); db.commit()
    response = c["client"].get(f'/api/assessments/{run.id}/objectives')
    assert response.json()["frameworkVersion"] == "test-v1"
    assert [item["statement"] for item in response.json()["items"]] == ["Original objective"]
    assert c["client"].get(f'/api/assessments/{run.id}/objectives/{c["identifier"]}').status_code == 404


def test_objective_routes_require_login(context):
    c = context
    c["client"].delete('/api/session')
    assert c["client"].get(c["base"]).status_code == 401
    assert c["client"].put(c["base"] + '/review', json=payload()).status_code == 401

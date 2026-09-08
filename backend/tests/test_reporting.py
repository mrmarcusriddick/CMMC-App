from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.models import ObjectivePoamLink, PoamItem
from test_access_and_screenshots import client
from test_objective_reviews import context, payload


def test_summary_includes_unreviewed_objectives_and_separates_technical_signals(context):
    c = context
    report = c["client"].get(f'/api/assessments/{c["run"]}/summary').json()
    assert report["totals"]["objectives"] == 320
    assert report["totals"]["notStarted"] == 320
    assert report["totals"]["met"] == 0
    assert report["totals"]["complete"] == 0
    assert report["technicalFindings"][0]["status"] == "MANUAL_REVIEW"
    assert len(report["queues"]["missingOwner"]) == 320
    assert len(report["queues"]["missingEvidence"]) == 320
    assert sum(item["total"] for item in report["domains"]) == 320


def test_latest_revision_only_and_provisional_decisions(context):
    c = context
    c["client"].put(c["base"] + '/review', json=payload())
    c["client"].put(c["base"] + '/review', json=payload(expected_revision=1, status="IN_REVIEW", decision="NOT_MET"))
    report = c["client"].get(f'/api/assessments/{c["run"]}/summary').json()
    assert report["totals"]["complete"] == 0
    assert report["totals"]["inReview"] == 1
    assert report["totals"]["met"] == report["totals"]["notMet"] == 0
    assert report["totals"]["draftDecisions"] == 1
    assert c["identifier"] in report["queues"]["pendingDecision"]
    assert c["identifier"] not in report["queues"]["missingOwner"]
    other = c["client"].get(f'/api/assessments/{c["other"]}/summary').json()
    assert other["totals"]["notStarted"] == 320


def test_completed_not_applicable_counts_in_workflow_progress_and_attachments(context):
    c = context
    c["client"].put(c["base"] + '/review', json=payload(decision="NOT_APPLICABLE", resources=[{"kind": "SCREENSHOT", "id": c["screenshot"]}]))
    report = c["client"].get(f'/api/assessments/{c["run"]}/summary').json()
    assert report["totals"]["complete"] == report["totals"]["notApplicable"] == 1
    assert report["totals"]["completionPercent"] == 0.3
    assert c["identifier"] not in report["queues"]["pendingDecision"]
    assert c["identifier"] not in report["queues"]["missingEvidence"]
    assert sum(item["complete"] for item in report["domains"]) == 1


def test_poam_links_are_run_scoped_and_overdue_excludes_closed_and_due_today(context):
    c = context
    db = c["db"]
    today = datetime.now(UTC).replace(tzinfo=None)
    for index, (run_id, status, due, finding) in enumerate([
        (c["run"], "OPEN", today - timedelta(days=2), None),
        (c["run"], "CLOSED", today - timedelta(days=2), None),
        (c["run"], "COMPLETE", today - timedelta(days=2), None),
        (c["run"], "OPEN", today, None),
        (c["other"], "OPEN", today - timedelta(days=2), None),
        (c["run"], "OPEN", today - timedelta(days=2), c["finding"]),
    ]):
        item = PoamItem(title=f"Gap {index}", status=status, target_date=due, finding_id=finding)
        db.add(item); db.flush()
        if not finding:
            db.add(ObjectivePoamLink(run_id=run_id, objective_identifier=c["identifier"], poam_id=item.id, request_key=str(uuid4())))
    db.commit()
    report = c["client"].get(f'/api/assessments/{c["run"]}/summary').json()
    assert len(report["poam"]) == 5
    assert report["totals"]["openGaps"] == 3
    assert report["totals"]["overdueGaps"] == 2


def test_exports_include_rationale_hashes_and_escape_markdown(context):
    c = context
    c["client"].put(c["base"] + '/review', json=payload(notes="<script>alert(1)</script>\n# forged heading", resources=[{"kind": "SCREENSHOT", "id": c["screenshot"]}]))
    prefix = f'/api/assessments/{c["run"]}'
    result = c["client"].get(prefix + '/review-report.json')
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert 'attachment;' in result.headers["content-disposition"]
    item = next(item for item in result.json()["objectives"] if item["identifier"] == c["identifier"])
    assert item["review"]["resources"][0]["sha256"] == 'c' * 64
    markdown = c["client"].get(prefix + '/review-report.md').text
    assert 'Technical findings (separate from reviewer decisions)' in markdown
    assert 'c' * 64 in markdown
    assert '<script>' not in markdown
    assert '\n# forged heading' not in markdown
    assert 'reviewer' in markdown


def test_summary_and_exports_require_existing_run_and_login(context):
    c = context
    for suffix in ['summary', 'review-report.json', 'review-report.md']:
        assert c["client"].get('/api/assessments/missing/' + suffix).status_code == 404
    c["client"].delete('/api/session')
    for suffix in ['summary', 'review-report.json', 'review-report.md']:
        assert c["client"].get(f'/api/assessments/{c["run"]}/' + suffix).status_code == 401

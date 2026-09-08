"""Current review progress for a single run; never a certification score."""
from collections import Counter
from datetime import UTC, datetime
import html
import re

from fastapi import APIRouter, Depends, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from .database import get_session
from .models import AssessmentRun, Finding, ObjectivePoamLink, PoamItem
from .objectives import list_objectives
from .poam_workflow import rereview_requests

router = APIRouter(prefix="/api/assessments")


def assessment_report(db: Session, run_id: str) -> dict:
    catalog = list_objectives(run_id, db)
    run = db.get(AssessmentRun, run_id)
    items = catalog["items"]
    known = {item["identifier"] for item in items}
    statuses = Counter(item["review"]["status"] for item in items)
    # Only completed reviews contribute to finalized decision totals.
    decisions = Counter(item["review"]["decision"] for item in items if item["review"]["status"] == "COMPLETE")
    draft_decisions = Counter(item["review"]["decision"] for item in items if item["review"]["status"] != "COMPLETE" and item["review"]["decision"] != "NOT_ASSESSED")
    findings = db.scalars(select(Finding).where(Finding.run_id == run_id).options(
        selectinload(Finding.framework_objective), selectinload(Finding.objective))).all()
    technical = [{"id": item.id, "identifier": (item.framework_objective or item.objective).identifier,
                  "status": item.status, "detail": item.detail} for item in findings]
    rows = db.execute(select(PoamItem, ObjectivePoamLink, Finding).outerjoin(ObjectivePoamLink, ObjectivePoamLink.poam_id == PoamItem.id)
        .outerjoin(Finding, Finding.id == PoamItem.finding_id).where(or_(ObjectivePoamLink.run_id == run_id, Finding.run_id == run_id))
        .order_by(PoamItem.target_date, PoamItem.created_at)).all()
    today = datetime.now(UTC).date()
    gaps = []
    for item, link, finding in rows:
        identifier = link.objective_identifier if link and link.run_id == run_id else (finding.framework_objective or finding.objective).identifier
        if identifier not in known:
            continue
        closed = item.status in {"COMPLETE", "CLOSED", "CANCELLED"}
        due = item.target_date
        due_date = (due.astimezone(UTC) if due and due.tzinfo else due).date() if due else None
        gaps.append({"id": item.id, "identifier": identifier, "title": item.title, "status": item.status,
                     "owner": item.owner, "description": item.description, "targetDate": due,
                     "open": not closed, "overdue": bool(not closed and due_date and due_date < today)})
    domains = []
    for domain in sorted({item["domain"] for item in items}):
        subset = [item for item in items if item["domain"] == domain]
        count = Counter(item["review"]["status"] for item in subset)
        domains.append({"domain": domain, "total": len(subset), "notStarted": count["NOT_STARTED"],
                        "inReview": count["IN_REVIEW"], "complete": count["COMPLETE"]})
    queues = {"missingOwner": [], "missingEvidence": [], "pendingDecision": [],
              "reReview": sorted({row["identifier"] for row in rereview_requests(db, run_id) if row["identifier"] in known})}
    for item in items:
        review = item["review"]
        if not review["owner"].strip():
            queues["missingOwner"].append(item["identifier"])
        if not review["resources"]:
            queues["missingEvidence"].append(item["identifier"])
        if review["status"] != "COMPLETE" or review["decision"] == "NOT_ASSESSED":
            queues["pendingDecision"].append(item["identifier"])
    return {"runId": run.id, "tenantId": run.tenant_id, "startedAt": run.started_at, "generatedAt": datetime.now(UTC),
            "framework": {"version": run.framework_release.version, "status": run.framework_release.status,
                          "sourceUrl": run.framework_release.source_url} if run.framework_release else {"status": "UNVERIFIED_SEED"},
            "totals": {"objectives": len(items), "notStarted": statuses["NOT_STARTED"], "inReview": statuses["IN_REVIEW"],
                       "complete": statuses["COMPLETE"], "completionPercent": round(100 * statuses["COMPLETE"] / len(items), 1) if items else 0,
                       "met": decisions["MET"], "notMet": decisions["NOT_MET"], "notApplicable": decisions["NOT_APPLICABLE"],
                       "draftDecisions": sum(draft_decisions.values()), "openGaps": sum(item["open"] for item in gaps),
                       "overdueGaps": sum(item["overdue"] for item in gaps)},
            "domains": domains, "queues": queues, "objectives": items, "technicalFindings": technical, "poam": gaps,
            "definitions": {"completion": "Completed human reviews divided by all objectives, including not applicable. This is workflow progress, not a compliance score.",
                            "decisions": "Decision totals count completed reviews only; provisional decisions are reported separately.",
                            "missingEvidence": "No evidence or supporting-record attachments in the latest review. Discovery availability alone does not clear this queue.",
                            "overdue": "A POA&M that is not complete, closed, or cancelled and whose target date is before today in UTC.",
                            "scope": "Latest saved review per objective, for this assessment run and its catalog release. Queues may overlap."}}


def md(value) -> str:
    value = html.escape(str(value or ""), quote=False).replace("\r", " ").replace("\n", " ")
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", value)


def report_markdown(report: dict) -> str:
    totals = report["totals"]
    lines = ["# Assessment review report", "", f"Run: {md(report['runId'])}", f"Tenant: {md(report['tenantId'])}",
             f"Generated: {md(report['generatedAt'].isoformat())}",
             f"Baseline: {md(report['framework'].get('version', 'Unverified seed'))} ({md(report['framework']['status'])})", "",
             "## Review progress", "", report["definitions"]["completion"], "", report["definitions"]["decisions"], "",
             f"Completed: {totals['complete']}/{totals['objectives']} ({totals['completionPercent']}%)",
             f"Not started: {totals['notStarted']}; in review: {totals['inReview']}; provisional decisions: {totals['draftDecisions']}",
             f"Finalized decisions: met {totals['met']}; not met {totals['notMet']}; not applicable {totals['notApplicable']}", "",
             "| Domain | Total | Not started | In review | Complete |", "|---|---:|---:|---:|---:|"]
    for domain in report["domains"]:
        lines.append(f"| {md(domain['domain'])} | {domain['total']} | {domain['notStarted']} | {domain['inReview']} | {domain['complete']} |")
    lines += ["", "## Review queues", "", report["definitions"]["scope"], "", report["definitions"]["missingEvidence"], ""]
    for name, ids in report["queues"].items():
        lines += [f"### {md(name)} ({len(ids)})", "", ", ".join(md(identifier) for identifier in ids) or "None", ""]
    lines += ["## Objective reviews", ""]
    for item in report["objectives"]:
        review = item["review"]
        lines += [f"### {md(item['identifier'])}", "", md(item["statement"]), "",
                  f"Owner: {md(review['owner']) or 'Unassigned'}; status: {md(review['status'])}; decision: {md(review['decision'])}",
                  f"Revision: {review['revision']}; recorded by: {md(review.get('recordedBy')) or 'Not reviewed'}; recorded at: {md(review.get('recordedAt'))}", "",
                  "Rationale:", "", *["> " + md(line) for line in (review["notes"] or "No rationale recorded.").splitlines()], "", "Evidence references:", ""]
        for ref in review["resources"]:
            lines.append(f"- {md(ref['kind'])}: {md(ref['label'])}; ID: {md(ref['id'])}; SHA-256: {md(ref.get('sha256')) or 'Not available'}")
        if not review["resources"]:
            lines.append("No attachments.")
        lines.append("")
    lines += ["## Technical findings (separate from reviewer decisions)", ""]
    for finding in report["technicalFindings"]:
        lines += [f"- {md(finding['identifier'])}: {md(finding['status'])} — {md(finding['detail'])}"]
    lines += ["", "## Linked POA&M items", "", report["definitions"]["overdue"], ""]
    for gap in report["poam"]:
        lines += [f"- {md(gap['identifier'])}: {md(gap['title'])}; ID: {md(gap['id'])}; status: {md(gap['status'])}; owner: {md(gap['owner']) or 'Unassigned'}; target: {md(gap['targetDate']) or 'Not set'}; overdue: {gap['overdue']}"]
    if not report["poam"]:
        lines.append("No linked POA&M items.")
    return "\n".join(lines) + "\n"


@router.get("/{run_id}/summary")
def summary(run_id: str, db: Session = Depends(get_session)):
    return assessment_report(db, run_id)


@router.get("/{run_id}/review-report.json")
def download_json(run_id: str, db: Session = Depends(get_session)):
    report = assessment_report(db, run_id)
    return JSONResponse(jsonable_encoder(report), headers={"Content-Disposition": f'attachment; filename="assessment-{report["runId"]}-review.json"'})


@router.get("/{run_id}/review-report.md")
def download_markdown(run_id: str, db: Session = Depends(get_session)):
    report = assessment_report(db, run_id)
    return Response(report_markdown(report), media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="assessment-{report["runId"]}-review.md"'})

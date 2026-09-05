import json
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload
from .models import AssessmentRun, Finding


def objective_identifier(finding: Finding) -> str:
    return (finding.framework_objective or finding.objective).identifier


def ssp_markdown(session: Session, run_id: str) -> str:
    run = session.scalar(select(AssessmentRun).where(AssessmentRun.id == run_id))
    if not run:
        raise LookupError("Assessment run not found")
    findings = session.scalars(select(Finding).options(joinedload(Finding.objective), joinedload(Finding.framework_objective)).where(Finding.run_id == run_id)).unique().all()
    baseline = f"CMMC Level {run.framework_release.level} v{run.framework_release.version} ({run.framework_release.status})" if run.framework_release else "Legacy development catalog"
    lines = ["# System Security Plan", "", f"Tenant: `{run.tenant_id}`", f"Assessment run: `{run.id}`", f"Framework baseline: {baseline}", ""]
    for finding in findings:
        evidence_names = ", ".join(f"evidence-{item.id}.json" for item in finding.evidence) or "No evidence captured"
        lines += [f"## {objective_identifier(finding)}", f"**Status:** {finding.status}", "", f"**How the practice is implemented:** {finding.detail}", "", f"**Evidence file name references:** {evidence_names}", ""]
    return "\n".join(lines)


def evidence_json(session: Session, run_id: str) -> dict:
    findings = session.scalars(select(Finding).options(joinedload(Finding.objective), joinedload(Finding.framework_objective), joinedload(Finding.evidence)).where(Finding.run_id == run_id)).unique().all()
    return {"runId": run_id, "objectives": [{"identifier": objective_identifier(f), "status": f.status, "detail": f.detail, "evidence": [{"id": e.id, "source": e.source, "payload": e.payload, "payloadHash": e.payload_hash, "chainHash": e.chain_hash, "capturedAt": e.captured_at.isoformat()} for e in f.evidence]} for f in findings]}

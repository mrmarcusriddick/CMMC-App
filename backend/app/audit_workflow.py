"""Human audit-log reviews, with run-scoped evidence and append-only history."""
from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_session
from .models import (AssessmentRun, AuditEvidenceReview, AuditReviewRevision, AuditGapLink,
                     EvidenceLog, Finding, ScreenshotEvidence, PoamItem, ObjectivePoamLink)
from .objectives import run_catalog, resource_out

router = APIRouter(prefix="/api")


def state(db, run):
    review = db.scalar(select(AuditEvidenceReview).where(AuditEvidenceReview.run_id == run.id))
    history = db.scalars(select(AuditReviewRevision).where(AuditReviewRevision.run_id == run.id)
                         .order_by(AuditReviewRevision.revision.desc())).all()
    value = {"revision": 0, "reviewOwner": review.review_owner or "" if review else "",
             "retentionDays": review.retention_days if review else None,
             "reviewFrequency": review.review_frequency or "" if review else "",
             "requiredEventCategories": review.required_event_categories if review else [],
             "status": review.status if review else "NOT_STARTED", "notes": review.notes or "" if review else "",
             "nextReviewDate": None, "resources": []}
    if history:
        value = dict(history[0].snapshot)
    return value, history, review


@router.get("/audit-reviews")
def register(db: Session = Depends(get_session)):
    rows = []
    for run in db.scalars(select(AssessmentRun).order_by(AssessmentRun.started_at.desc())).all():
        value, _, _ = state(db, run)
        rows.append({**value, "runId": run.id, "tenantId": run.tenant_id, "startedAt": run.started_at,
                     "overdue": bool(value["nextReviewDate"] and date.fromisoformat(value["nextReviewDate"]) < datetime.now(UTC).date())})
    return {"items": rows}


@router.get("/assessments/{run_id}/audit-review")
def detail(run_id: str, db: Session = Depends(get_session)):
    run, objectives = run_catalog(db, run_id)
    value, history, _ = state(db, run)
    evidence = db.scalars(select(EvidenceLog).join(Finding).where(Finding.run_id == run_id)).all()
    gaps = db.scalars(select(PoamItem).join(AuditGapLink, AuditGapLink.poam_id == PoamItem.id)
                      .where(AuditGapLink.run_id == run_id).order_by(PoamItem.created_at.desc())).all()
    return {"runId": run.id, "tenantId": run.tenant_id, "review": value,
            "history": [{"revision": row.revision, "recordedAt": row.recorded_at,
                         "recordedBy": row.recorded_by, "snapshot": row.snapshot} for row in history],
            "evidence": [resource_out("DISCOVERY", item) for item in evidence],
            "objectives": [{"identifier": item.identifier, "statement": item.statement} for item in objectives if item.identifier.startswith("AU.")],
            "poam": [{"id": item.id, "title": item.title, "status": item.status} for item in gaps]}


class Resource(BaseModel):
    kind: Literal["SCREENSHOT", "DISCOVERY"]
    id: str = Field(min_length=1, max_length=36)


class ReviewRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    review_owner: str = Field(default="", max_length=200)
    retention_days: int | None = Field(default=None, ge=0, le=36500)
    review_frequency: str = Field(default="", max_length=100)
    required_event_categories: list[str] = Field(default_factory=list, max_length=30)
    status: Literal["NOT_STARTED", "IN_REVIEW", "SUPPORTED", "GAP", "NOT_APPLICABLE"]
    notes: str = Field(default="", max_length=20000)
    next_review_date: date | None = None
    resources: list[Resource] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def valid_conclusion(self):
        self.review_owner, self.notes, self.review_frequency = self.review_owner.strip(), self.notes.strip(), self.review_frequency.strip()
        self.required_event_categories = list(dict.fromkeys(value.strip() for value in self.required_event_categories))
        if any(not value or len(value) > 200 for value in self.required_event_categories):
            raise ValueError("Event categories must contain 1–200 characters each.")
        if self.status in {"SUPPORTED", "GAP", "NOT_APPLICABLE"} and (not self.review_owner or not self.notes):
            raise ValueError("A review conclusion requires an owner and rationale.")
        if self.status == "SUPPORTED" and (not self.resources or self.retention_days is None or not self.review_frequency or not self.required_event_categories):
            raise ValueError("Supported requires evidence, retention, review frequency, and required event categories.")
        return self


@router.put("/assessments/{run_id}/audit-review")
def save(run_id: str, body: ReviewRequest, db: Session = Depends(get_session)):
    run = db.scalar(select(AssessmentRun).where(AssessmentRun.id == run_id).with_for_update())
    if not run:
        raise HTTPException(404, "Assessment run not found.")
    current, history, review = state(db, run)
    if current["revision"] != body.expected_revision:
        raise HTTPException(409, "This review changed in another session. Reload the saved review before saving.")
    resources, seen = [], set()
    for ref in body.resources:
        if (ref.kind, ref.id) in seen:
            continue
        seen.add((ref.kind, ref.id))
        item = db.get(ScreenshotEvidence if ref.kind == "SCREENSHOT" else EvidenceLog, ref.id)
        if not item or (ref.kind == "DISCOVERY" and item.finding.run_id != run_id):
            raise HTTPException(422, "Evidence is missing or belongs to another assessment run.")
        resources.append(resource_out(ref.kind, item))
    if not history:
        db.add(AuditReviewRevision(run_id=run_id, revision=0, snapshot=current, recorded_by="original baseline"))
    if not review:
        review = AuditEvidenceReview(run_id=run_id)
        db.add(review)
    review.review_owner, review.retention_days, review.review_frequency = body.review_owner, body.retention_days, body.review_frequency
    review.required_event_categories, review.status, review.notes = body.required_event_categories, body.status, body.notes
    snapshot = {"revision": current["revision"] + 1, "reviewOwner": body.review_owner,
                "retentionDays": body.retention_days, "reviewFrequency": body.review_frequency,
                "requiredEventCategories": body.required_event_categories, "status": body.status, "notes": body.notes,
                "nextReviewDate": body.next_review_date.isoformat() if body.next_review_date else None, "resources": resources}
    db.add(AuditReviewRevision(run_id=run_id, revision=snapshot["revision"], snapshot=snapshot, recorded_by=get_settings().app_username))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This review changed in another session. Reload before saving.") from exc
    return detail(run_id, db)


class GapRequest(BaseModel):
    request_key: UUID
    expected_revision: int = Field(ge=1)
    identifier: str = Field(max_length=40)
    title: str = Field(min_length=3, max_length=240)
    target_date: date | None = None


@router.post("/assessments/{run_id}/audit-review/poam", status_code=201)
def create_gap(run_id: str, body: GapRequest, db: Session = Depends(get_session)):
    run, objectives = run_catalog(db, run_id)
    db.scalar(select(AssessmentRun).where(AssessmentRun.id == run_id).with_for_update())
    existing = db.scalar(select(AuditGapLink).where(AuditGapLink.run_id == run_id, AuditGapLink.request_key == str(body.request_key)))
    if existing:
        return {"id": existing.poam_id}
    current, _, _ = state(db, run)
    if current["revision"] != body.expected_revision:
        raise HTTPException(409, "The audit review changed. Reload before creating a gap.")
    if current["status"] != "GAP":
        raise HTTPException(422, "Save a Gap conclusion before creating a POA&M item.")
    if len(body.title.strip()) < 3 or not any(item.identifier == body.identifier and item.identifier.startswith("AU.") for item in objectives):
        raise HTTPException(422, "Enter a title and select an audit objective from this run.")
    item = PoamItem(title=body.title.strip(), description=current["notes"], owner=current["reviewOwner"],
                    status="OPEN", target_date=datetime.combine(body.target_date, datetime.min.time()) if body.target_date else None)
    db.add(item); db.flush()
    db.add(AuditGapLink(run_id=run_id, poam_id=item.id, request_key=str(body.request_key)))
    db.add(ObjectivePoamLink(run_id=run_id, objective_identifier=body.identifier, poam_id=item.id, request_key=str(body.request_key)))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Gap creation conflicted. Retry with the same request.") from exc
    return {"id": item.id}

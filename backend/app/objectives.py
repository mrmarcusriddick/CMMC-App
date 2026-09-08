"""Run-scoped human reviews; technical findings are never overwritten."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .database import get_session
from .models import (AssessmentRun, AssessmentObjective, FrameworkAssessmentObjective, FrameworkPractice,
                     Finding, EvidenceLog, ScreenshotEvidence, ManagedAccount, InventoryAsset, ChangeRecord,
                     PolicyException, ObjectiveReviewRevision, ObjectivePoamLink, PoamItem)

from .poam_workflow import rereview_requests

router = APIRouter(prefix="/api")
ResourceKind = Literal["SCREENSHOT", "DISCOVERY", "ACCOUNT", "ASSET", "CHANGE", "POLICY_EXCEPTION"]
RESOURCE_MODELS = {"SCREENSHOT": ScreenshotEvidence, "DISCOVERY": EvidenceLog, "ACCOUNT": ManagedAccount,
                   "ASSET": InventoryAsset, "CHANGE": ChangeRecord, "POLICY_EXCEPTION": PolicyException}


def run_catalog(db, run_id):
    run = db.get(AssessmentRun, run_id)
    if not run:
        raise HTTPException(404, "Assessment run not found.")
    if run.framework_release_id:
        items = db.scalars(select(FrameworkAssessmentObjective).join(FrameworkPractice).where(
            FrameworkPractice.release_id == run.framework_release_id).options(selectinload(FrameworkAssessmentObjective.practice))).all()
    else:
        items = db.scalars(select(AssessmentObjective).options(selectinload(AssessmentObjective.practice))).all()
    return run, sorted(items, key=lambda item: (item.practice.identifier, item.ordinal))


def objective_context(db, run_id, identifier):
    run, items = run_catalog(db, run_id)
    objective = next((item for item in items if item.identifier == identifier), None)
    if not objective:
        raise HTTPException(404, "Objective is not part of this assessment's catalog.")
    return run, objective


def revisions(db, run_id, identifier):
    return db.scalars(select(ObjectiveReviewRevision).where(ObjectiveReviewRevision.run_id == run_id,
        ObjectiveReviewRevision.objective_identifier == identifier).order_by(ObjectiveReviewRevision.revision.desc())).all()


def review_out(item):
    if not item:
        return {"revision": 0, "owner": "", "status": "NOT_STARTED", "decision": "NOT_ASSESSED", "notes": "", "resources": []}
    return {"revision": item.revision, "owner": item.owner, "status": item.status, "decision": item.decision,
            "notes": item.notes, "resources": item.resources, "recordedBy": item.recorded_by, "recordedAt": item.recorded_at}


def resource_out(kind, item):
    label = (getattr(item, "title", None) or getattr(item, "name", None) or
             getattr(item, "display_name", None) or getattr(item, "account_identifier", None) or getattr(item, "source", None))
    result = {"kind": kind, "id": item.id, "label": label}
    if kind == "SCREENSHOT":
        result.update(sha256=item.sha256, url=f"/api/screenshots/{item.id}/content", containsCui=item.contains_cui)
    if kind == "DISCOVERY":
        result.update(sha256=item.payload_hash, url=f"/api/assessments/{item.finding.run_id}/evidence.json")
    return result


def belongs(finding, run, objective):
    return (finding.run_id == run.id and
            (finding.framework_objective_id == objective.id if run.framework_release_id else finding.objective_id == objective.id))


@router.get("/assessments/{run_id}/objectives")
def list_objectives(run_id: str, db: Session = Depends(get_session)):
    run, items = run_catalog(db, run_id)
    history = db.scalars(select(ObjectiveReviewRevision).where(ObjectiveReviewRevision.run_id == run_id)
                         .order_by(ObjectiveReviewRevision.revision)).all()
    latest = {item.objective_identifier: item for item in history}
    return {"runId": run.id, "tenantId": run.tenant_id,
            "frameworkVersion": run.framework_release.version if run.framework_release else None,
            "items": [{"identifier": item.identifier, "statement": item.statement, "practiceTitle": item.practice.title,
                       "domain": item.practice.domain_code if run.framework_release_id else item.practice.domain.code,
                       "review": review_out(latest.get(item.identifier))} for item in items]}


@router.get("/assessments/{run_id}/objectives/{identifier}")
def objective_detail(run_id: str, identifier: str, db: Session = Depends(get_session)):
    run, objective = objective_context(db, run_id, identifier)
    history = revisions(db, run_id, identifier)
    findings = [item for item in db.scalars(select(Finding).where(Finding.run_id == run_id)
                .options(selectinload(Finding.evidence))).all() if belongs(item, run, objective)]
    poam_ids = db.scalars(select(ObjectivePoamLink.poam_id).where(ObjectivePoamLink.run_id == run_id,
                         ObjectivePoamLink.objective_identifier == identifier)).all()
    finding_ids = [item.id for item in findings]
    poam = db.scalars(select(PoamItem).where((PoamItem.id.in_(poam_ids)) | (PoamItem.finding_id.in_(finding_ids)))
                     .order_by(PoamItem.created_at.desc())).all()
    return {"rereviewRequests": rereview_requests(db, run_id, identifier), "identifier": identifier, "statement": objective.statement, "practiceTitle": objective.practice.title,
            "practiceStatement": getattr(objective.practice, "statement", None), "runId": run.id, "tenantId": run.tenant_id,
            "framework": {"version": run.framework_release.version, "status": run.framework_release.status,
                          "sourceUrl": run.framework_release.source_url} if run.framework_release else {"status": "UNVERIFIED_SEED"},
            "review": review_out(history[0] if history else None), "history": [review_out(item) for item in history],
            "findings": [{"id": item.id, "status": item.status, "detail": item.detail,
                          "evidence": [resource_out("DISCOVERY", evidence) for evidence in item.evidence]} for item in findings],
            "poam": [{"id": item.id, "title": item.title, "status": item.status, "owner": item.owner, "targetDate": item.target_date} for item in poam]}


@router.get("/assessments/{run_id}/objectives/{identifier}/resources")
def available_resources(run_id: str, identifier: str, kind: ResourceKind = "SCREENSHOT", q: str = Query("", max_length=200), db: Session = Depends(get_session)):
    run, objective = objective_context(db, run_id, identifier)
    model = RESOURCE_MODELS[kind]
    query = select(model)
    if kind == "DISCOVERY":
        query = query.join(Finding).where(Finding.run_id == run_id)
        query = query.where(Finding.framework_objective_id == objective.id) if run.framework_release_id else query.where(Finding.objective_id == objective.id)
        field = EvidenceLog.source
    else:
        field = {"SCREENSHOT": ScreenshotEvidence.title, "ACCOUNT": ManagedAccount.account_identifier,
                 "ASSET": InventoryAsset.name, "CHANGE": ChangeRecord.title, "POLICY_EXCEPTION": PolicyException.title}[kind]
    if q.strip():
        query = query.where(field.icontains(q.strip(), autoescape=True))
    rows = db.scalars(query.order_by(field, model.id).limit(101)).all()
    return {"items": [resource_out(kind, item) for item in rows[:100]], "hasMore": len(rows) > 100}


class ResourceReference(BaseModel):
    kind: ResourceKind
    id: str = Field(min_length=1, max_length=36)


class ReviewRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    owner: str = Field(default="", max_length=200)
    status: Literal["NOT_STARTED", "IN_REVIEW", "COMPLETE"] = "NOT_STARTED"
    decision: Literal["NOT_ASSESSED", "MET", "NOT_MET", "NOT_APPLICABLE"] = "NOT_ASSESSED"
    notes: str = Field(default="", max_length=20000)
    resources: list[ResourceReference] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def complete_review(self):
        self.owner, self.notes = self.owner.strip(), self.notes.strip()
        if self.status == "COMPLETE" and (self.decision == "NOT_ASSESSED" or not self.owner or not self.notes):
            raise ValueError("A complete review requires an owner, decision, and rationale.")
        return self


@router.put("/assessments/{run_id}/objectives/{identifier}/review")
def save_review(run_id: str, identifier: str, body: ReviewRequest, db: Session = Depends(get_session)):
    run, objective = objective_context(db, run_id, identifier)
    history = revisions(db, run_id, identifier)
    current = history[0].revision if history else 0
    if body.expected_revision != current:
        raise HTTPException(409, "This review changed in another session. Reload the objective before saving.")
    resources, seen = [], set()
    for ref in body.resources:
        if (ref.kind, ref.id) in seen:
            continue
        seen.add((ref.kind, ref.id))
        item = db.get(RESOURCE_MODELS[ref.kind], ref.id)
        if not item or (ref.kind == "DISCOVERY" and not belongs(item.finding, run, objective)):
            raise HTTPException(422, "A linked resource is missing or belongs to another assessment objective.")
        resources.append(resource_out(ref.kind, item))
    revision = ObjectiveReviewRevision(run_id=run_id, objective_identifier=identifier, revision=current + 1,
        owner=body.owner, status=body.status, decision=body.decision, notes=body.notes, resources=resources,
        recorded_by=get_settings().app_username)
    db.add(revision)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This review changed in another session. Reload before saving.") from exc
    return review_out(revision)


class ObjectivePoamRequest(BaseModel):
    request_key: UUID
    expected_revision: int = Field(ge=1)
    title: str = Field(min_length=3, max_length=240)
    description: str = Field(default="", max_length=20000)
    owner: str = Field(default="", max_length=200)
    target_date: datetime | None = None


@router.post("/assessments/{run_id}/objectives/{identifier}/poam", status_code=201)
def create_objective_poam(run_id: str, identifier: str, body: ObjectivePoamRequest, db: Session = Depends(get_session)):
    objective_context(db, run_id, identifier)
    key = str(body.request_key)
    existing_query = select(ObjectivePoamLink).where(ObjectivePoamLink.run_id == run_id,
        ObjectivePoamLink.objective_identifier == identifier, ObjectivePoamLink.request_key == key)
    existing = db.scalar(existing_query)
    if existing:
        return {"id": existing.poam_id}
    history = revisions(db, run_id, identifier)
    if not history or history[0].revision != body.expected_revision:
        raise HTTPException(409, "Reload the latest review before creating a POA&M item.")
    if history[0].decision != "NOT_MET":
        raise HTTPException(409, "Save a Not met decision before creating a gap item.")
    if len(body.title.strip()) < 3:
        raise HTTPException(422, "Enter a descriptive POA&M title.")
    item = PoamItem(title=body.title.strip(), description=body.description.strip(), owner=body.owner.strip() or None,
                    target_date=body.target_date, status="OPEN")
    db.add(item)
    db.flush()
    db.add(ObjectivePoamLink(run_id=run_id, objective_identifier=identifier, poam_id=item.id, request_key=key))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(existing_query)
        if existing:
            return {"id": existing.poam_id}
        raise HTTPException(409, "The POA&M could not be created. Reload and try again.") from exc
    return {"id": item.id}

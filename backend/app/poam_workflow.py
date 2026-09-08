from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_session
from .models import PoamItem, PoamRevision, ObjectiveReviewRevision, ScreenshotEvidence

router = APIRouter(prefix="/api/poam")


def linkage(item):
    if item.objective_link:
        return item.objective_link.run_id, item.objective_link.objective_identifier
    if item.finding:
        return item.finding.run_id, (item.finding.framework_objective or item.finding.objective).identifier
    return None, None


def history(db, item_id):
    return db.scalars(select(PoamRevision).where(PoamRevision.poam_id == item_id).order_by(PoamRevision.revision.desc())).all()


def current_state(item, revisions):
    last = revisions[0].snapshot if revisions else {}
    run_id, identifier = linkage(item)
    due = item.target_date
    today = datetime.now(UTC).date()
    return {"id": item.id, "revision": revisions[0].revision if revisions else 0, "title": item.title,
            "description": item.description or "", "owner": item.owner or "", "status": item.status,
            "targetDate": due.isoformat() if due else None, "evidenceReference": item.evidence_reference or "",
            "milestones": last.get("milestones", [{"title": value, "complete": False} for value in item.milestones]),
            "closureNotes": last.get("closureNotes", ""), "screenshots": last.get("screenshots", []),
            "runId": run_id, "identifier": identifier,
            "overdue": bool(due and due.date() < today and item.status not in {"COMPLETE", "CLOSED"})}


def rereview_requests(db, run_id, identifier=None):
    # Closure events preserve their original assessment linkage. A later completed review acknowledges them.
    revisions = db.scalars(select(PoamRevision).order_by(PoamRevision.recorded_at.desc())).all()
    latest = {}
    for review in db.scalars(select(ObjectiveReviewRevision).where(ObjectiveReviewRevision.run_id == run_id)
                             .order_by(ObjectiveReviewRevision.revision)).all():
        if review.status == "COMPLETE":
            latest[review.objective_identifier] = review.recorded_at
    pending = {}
    for revision in revisions:
        event = revision.snapshot
        objective = event.get("identifier")
        if not event.get("closureEvent") or event.get("runId") != run_id or (identifier and objective != identifier):
            continue
        if objective not in latest or latest[objective] <= revision.recorded_at:
            pending.setdefault(revision.poam_id, {"poamId": revision.poam_id, "identifier": objective,
                "title": event["title"], "closedAt": revision.recorded_at})
    return list(pending.values())


@router.get("/register")
def register(db: Session = Depends(get_session)):
    rows = db.scalars(select(PoamItem).order_by(PoamItem.updated_at.desc())).all()
    all_history = db.scalars(select(PoamRevision).order_by(PoamRevision.revision.desc())).all()
    grouped = {}
    for revision in all_history:
        grouped.setdefault(revision.poam_id, []).append(revision)
    return {"items": [current_state(item, grouped.get(item.id, [])) for item in rows]}


@router.get("/{item_id}")
def detail(item_id: str, db: Session = Depends(get_session)):
    item = db.get(PoamItem, item_id)
    if not item:
        raise HTTPException(404, "POA&M item not found.")
    revisions = history(db, item_id)
    result = current_state(item, revisions)
    result["history"] = [{"revision": row.revision, "recordedAt": row.recorded_at,
                          "recordedBy": row.recorded_by, "snapshot": row.snapshot} for row in revisions]
    result["rereviewPending"] = bool(result["runId"] and any(row["poamId"] == item_id for row in rereview_requests(db, result["runId"], result["identifier"])))
    return result


class Milestone(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    complete: bool = False


class UpdateRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    title: str = Field(min_length=3, max_length=240)
    description: str = Field(default="", max_length=20000)
    owner: str = Field(default="", max_length=200)
    status: Literal["OPEN", "IN_PROGRESS", "BLOCKED", "COMPLETE", "CLOSED"]
    target_date: datetime | None = None
    milestones: list[Milestone] = Field(default_factory=list, max_length=30)
    evidence_reference: str = Field(default="", max_length=5000)
    closure_notes: str = Field(default="", max_length=5000)
    screenshot_ids: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_completion(self):
        self.title, self.owner = self.title.strip(), self.owner.strip()
        self.evidence_reference, self.closure_notes = self.evidence_reference.strip(), self.closure_notes.strip()
        if len(self.title) < 3 or any(not item.title.strip() for item in self.milestones):
            raise ValueError("Enter a title and non-blank milestone descriptions.")
        if self.status in {"COMPLETE", "CLOSED"}:
            if not self.owner or not self.closure_notes or not (self.evidence_reference or self.screenshot_ids):
                raise ValueError("Completion and closure require an owner, closure notes, and evidence.")
            if any(not item.complete for item in self.milestones):
                raise ValueError("Finish all milestones before completing or closing the gap.")
        return self


@router.patch("/{item_id}")
def update(item_id: str, body: UpdateRequest, db: Session = Depends(get_session)):
    item = db.scalar(select(PoamItem).where(PoamItem.id == item_id).with_for_update())
    if not item:
        raise HTTPException(404, "POA&M item not found.")
    revisions = history(db, item_id)
    current = current_state(item, revisions)
    if current["revision"] != body.expected_revision:
        raise HTTPException(409, "This gap changed in another session. Reload before saving.")
    screenshots = []
    for screenshot_id in dict.fromkeys(body.screenshot_ids):
        shot = db.get(ScreenshotEvidence, screenshot_id)
        if not shot:
            raise HTTPException(422, "A selected screenshot no longer exists.")
        screenshots.append({"id": shot.id, "title": shot.title, "sha256": shot.sha256})
    # Preserve the pre-feature state as revision zero on first edit.
    if not revisions:
        db.add(PoamRevision(poam_id=item.id, revision=0, snapshot=current, recorded_by="legacy baseline"))
    closure_event = body.status == "CLOSED" and item.status != "CLOSED"
    item.title, item.description, item.owner, item.status = body.title, body.description.strip(), body.owner, body.status
    item.target_date = body.target_date.astimezone(UTC).replace(tzinfo=None) if body.target_date and body.target_date.tzinfo else body.target_date
    item.milestones = [value.title.strip() for value in body.milestones]
    item.evidence_reference = body.evidence_reference
    snapshot = {**current, "revision": current["revision"] + 1, "title": item.title, "description": item.description,
                "owner": item.owner, "status": item.status, "targetDate": item.target_date.isoformat() if item.target_date else None,
                "milestones": [{"title": value.title.strip(), "complete": value.complete} for value in body.milestones],
                "evidenceReference": body.evidence_reference, "closureNotes": body.closure_notes,
                "screenshots": screenshots, "closureEvent": closure_event}
    snapshot.pop("overdue", None)
    db.add(PoamRevision(poam_id=item.id, revision=current["revision"] + 1, snapshot=snapshot, recorded_by=get_settings().app_username))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This gap changed in another session. Reload before saving.") from exc
    return detail(item_id, db)

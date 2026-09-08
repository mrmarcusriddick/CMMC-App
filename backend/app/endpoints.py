"""Endpoint review state is independent from imported Intune observations."""
from datetime import datetime, UTC, date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_session
from .models import InventoryAsset, EndpointRevision, EndpointObservation, EndpointGapLink, ScreenshotEvidence, PoamItem, ObjectivePoamLink
from .objectives import run_catalog

router = APIRouter(prefix="/api/endpoints")
CHECKS = ("intune", "configuration", "bitlocker", "defender", "patching", "localAdmin", "deviceCompliance")


def asset_context(db, asset_id):
    asset = db.scalar(select(InventoryAsset).where(InventoryAsset.id == asset_id).with_for_update())
    if not asset or asset.asset_type != "HARDWARE":
        raise HTTPException(404, "Hardware endpoint not found.")
    return asset


def state(db, asset):
    rows = db.scalars(select(EndpointRevision).where(EndpointRevision.asset_id == asset.id).order_by(EndpointRevision.revision.desc())).all()
    review = rows[0].snapshot if rows else {"revision": 0, "platform": "UNKNOWN", "enclave": "", "tenantId": "", "scope": "UNKNOWN",
        "owner": "", "assignedUser": "", "notes": "", "evidenceReference": "", "screenshots": [], "nextReviewDate": None,
        "checks": {key: "UNKNOWN" for key in CHECKS}}
    observation = db.get(EndpointObservation, asset.id)
    return {"id": asset.id, "name": asset.name, "assetIdentifier": asset.asset_identifier,
        "inventoryRole": asset.system_role, "inventoryOwner": asset.owner, "inventoryCuiInScope": asset.cui_in_scope,
        "review": review, "observation": {"data": observation.payload, "observedAt": observation.observed_at} if observation else None,
        "overdue": bool(review["nextReviewDate"] and date.fromisoformat(review["nextReviewDate"]) < datetime.now(UTC).date())}, rows


def capture_observation(db, asset, device, tenant_id, synced_at):
    # Retain only documented inventory fields; no recovery keys or credentials.
    allowed = ("operatingSystem", "osVersion", "userPrincipalName", "lastSyncDateTime", "managementAgent", "complianceState", "isEncrypted", "serialNumber")
    row = db.get(EndpointObservation, asset.id)
    if not row:
        row = EndpointObservation(asset_id=asset.id); db.add(row)
    row.payload = {"tenantId": tenant_id, "source": "Microsoft Graph /deviceManagement/managedDevices",
                   **{key: device.get(key) for key in allowed}}
    row.observed_at = synced_at


@router.get("")
def register(db: Session = Depends(get_session)):
    return {"items": [state(db, asset)[0] for asset in db.scalars(select(InventoryAsset).where(InventoryAsset.asset_type == "HARDWARE").order_by(InventoryAsset.name)).all()]}


@router.get("/{asset_id}")
def detail(asset_id: str, db: Session = Depends(get_session)):
    asset = asset_context(db, asset_id)
    result, rows = state(db, asset)
    result["history"] = [{"revision": row.revision, "snapshot": row.snapshot, "recordedBy": row.recorded_by, "recordedAt": row.recorded_at} for row in rows]
    gaps = db.scalars(select(PoamItem).join(EndpointGapLink, EndpointGapLink.poam_id == PoamItem.id).where(EndpointGapLink.asset_id == asset_id)).all()
    result["poam"] = [{"id": row.id, "title": row.title, "status": row.status} for row in gaps]
    return result


class Review(BaseModel):
    expected_revision: int = Field(ge=0)
    platform: Literal["WINDOWS", "OTHER", "UNKNOWN"] = "UNKNOWN"
    enclave: str = Field(default="", max_length=200)
    tenantId: str = Field(default="", max_length=100)
    scope: Literal["UNKNOWN", "IN_SCOPE", "OUT_OF_SCOPE"] = "UNKNOWN"
    owner: str = Field(default="", max_length=200)
    assignedUser: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=20000)
    evidenceReference: str = Field(default="", max_length=5000)
    screenshot_ids: list[str] = Field(default_factory=list, max_length=30)
    nextReviewDate: date | None = None
    checks: dict[str, Literal["UNKNOWN", "VERIFIED", "GAP"]]

    @model_validator(mode="after")
    def validate_review(self):
        for key in ("enclave", "tenantId", "owner", "assignedUser", "notes", "evidenceReference"):
            setattr(self, key, getattr(self, key).strip())
        if set(self.checks) != set(CHECKS):
            raise ValueError("Include every endpoint readiness check.")
        if self.scope == "IN_SCOPE" and (not self.enclave or not self.tenantId):
            raise ValueError("In-scope endpoints require an enclave name and cloud tenant ID.")
        if any(value != "UNKNOWN" for value in self.checks.values()) and (not self.owner or not self.notes):
            raise ValueError("Reviewed checks require an owner and rationale.")
        if "VERIFIED" in self.checks.values() and not (self.evidenceReference or self.screenshot_ids):
            raise ValueError("Verified checks require an evidence reference or screenshot.")
        return self


@router.put("/{asset_id}")
def save(asset_id: str, body: Review, db: Session = Depends(get_session)):
    asset = asset_context(db, asset_id)
    current, rows = state(db, asset)
    imported_tenant = current["observation"]["data"].get("tenantId") if current["observation"] else None
    if body.tenantId and imported_tenant and body.tenantId != imported_tenant:
        raise HTTPException(422, "Cloud tenant ID must match this endpoint's imported tenant.")
    if body.expected_revision != current["review"]["revision"]:
        raise HTTPException(409, "Endpoint review changed. Reload the saved review before saving.")
    shots = []
    for shot_id in dict.fromkeys(body.screenshot_ids):
        shot = db.get(ScreenshotEvidence, shot_id)
        if not shot:
            raise HTTPException(422, "Screenshot evidence not found.")
        shots.append({"id": shot.id, "title": shot.title, "sha256": shot.sha256})
    snapshot = body.model_dump(mode="json", exclude={"expected_revision", "screenshot_ids"})
    snapshot.update(revision=body.expected_revision + 1, screenshots=shots)
    db.add(EndpointRevision(asset_id=asset_id, revision=snapshot["revision"], snapshot=snapshot, recorded_by=get_settings().app_username))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(409, "Endpoint review changed. Reload before saving.") from exc
    return detail(asset_id, db)


class Gap(BaseModel):
    expected_revision: int = Field(ge=1)
    request_key: UUID
    run_id: str
    identifier: str = Field(max_length=40)
    title: str = Field(min_length=3, max_length=240)


@router.post("/{asset_id}/poam", status_code=201)
def create_gap(asset_id: str, body: Gap, db: Session = Depends(get_session)):
    asset = asset_context(db, asset_id)
    existing = db.scalar(select(EndpointGapLink).where(EndpointGapLink.asset_id == asset_id, EndpointGapLink.request_key == str(body.request_key)))
    if existing:
        return {"id": existing.poam_id}
    current, _ = state(db, asset); review = current["review"]
    if review["revision"] != body.expected_revision:
        raise HTTPException(409, "Endpoint review changed. Reload before creating a gap.")
    run, objectives = run_catalog(db, body.run_id)
    observation = current["observation"]
    imported_tenant = observation["data"].get("tenantId") if observation else None
    if review["tenantId"] != run.tenant_id or (imported_tenant and imported_tenant != run.tenant_id):
        raise HTTPException(422, "Choose an assessment from this endpoint's cloud tenant.")
    if "GAP" not in review["checks"].values() or not any(row.identifier == body.identifier for row in objectives) or len(body.title.strip()) < 3:
        raise HTTPException(422, "Save a readiness gap, then select an objective and enter a title.")
    item = PoamItem(title=body.title.strip(), description=f"Endpoint: {asset.name}\nEnclave: {review['enclave']}\n{review['notes']}", owner=review["owner"], status="OPEN",
                    evidence_reference=review["evidenceReference"])
    db.add(item); db.flush()
    db.add(EndpointGapLink(asset_id=asset_id, poam_id=item.id, request_key=str(body.request_key)))
    db.add(ObjectivePoamLink(run_id=run.id, objective_identifier=body.identifier, poam_id=item.id, request_key=str(body.request_key)))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(409, "Gap creation conflicted. Retry the same request.") from exc
    return {"id": item.id}

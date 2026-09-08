import hashlib
import hmac
import json
from datetime import UTC, datetime
import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from .assessment import AUTOMATED_CHECKS, _canonical_hash
from .auth import protect_api, router as auth_router
from .screenshot_validation import read_image
from .objectives import router as objectives_router
from .catalog import seed_catalog
from .config import get_settings
from .database import Base, SessionLocal, engine, get_session, migrate_existing_schema
from .exports import evidence_json, ssp_markdown
from .graph import GraphClient
from .models import AssessmentObjective, AssessmentRun, AuditEvidenceReview, ChangeRecord, EvidenceLog, Finding, FrameworkAssessmentObjective, FrameworkPractice, FrameworkRelease, InventoryAsset, ManagedAccount, MicrosoftPlacematRelease, PoamItem, PolicyException, RemediationApproval, RemediationPlan, ScreenshotEvidence, TenantCheckRule
from .remediation import build_remediation_request, execution_allowed, expiry

app = FastAPI(title="CMMC Tenant Readiness API", version="0.1.0")
app.middleware("http")(protect_api)
app.include_router(auth_router)
app.include_router(objectives_router)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins.split(","), allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(engine)
    migrate_existing_schema()
    with SessionLocal() as session:
        seed_catalog(session)


class RunRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)


class ApprovalRequest(BaseModel):
    approver_id: str = Field(min_length=3, max_length=200)
    mfa_confirmed: bool


class AuditReviewRequest(BaseModel):
    retention_days: int | None = Field(default=None, ge=0, le=36500)
    review_owner: str | None = Field(default=None, max_length=200)
    review_frequency: str | None = Field(default=None, max_length=100)
    required_event_categories: list[str] = Field(default_factory=list, max_length=30)
    status: str = Field(default="NOT_STARTED", pattern="^(NOT_STARTED|IN_REVIEW|SUPPORTED|GAP|NOT_APPLICABLE)$")
    notes: str | None = Field(default=None, max_length=5000)


class PoamItemRequest(BaseModel):
    finding_id: str | None = Field(default=None, max_length=36)
    title: str = Field(min_length=3, max_length=240)
    description: str | None = Field(default=None, max_length=5000)
    owner: str | None = Field(default=None, max_length=200)
    status: str = Field(default="OPEN", pattern="^(OPEN|IN_PROGRESS|BLOCKED|COMPLETE|CLOSED)$")
    target_date: datetime | None = None
    milestones: list[str] = Field(default_factory=list, max_length=30)
    evidence_reference: str | None = Field(default=None, max_length=5000)


class PolicyExceptionRequest(BaseModel):
    objective_identifier: str | None = Field(default=None, max_length=40)
    title: str = Field(min_length=3, max_length=240)
    rationale: str = Field(min_length=3, max_length=5000)
    compensating_controls: str | None = Field(default=None, max_length=5000)
    owner: str | None = Field(default=None, max_length=200)
    status: str = Field(default="DRAFT", pattern="^(DRAFT|SUBMITTED|APPROVED|REJECTED|EXPIRED|CLOSED)$")
    expires_at: datetime | None = None
    reviewed_by: str | None = Field(default=None, max_length=200)


class ManagedAccountRequest(BaseModel):
    account_identifier: str = Field(min_length=3, max_length=320)
    display_name: str | None = Field(default=None, max_length=240)
    account_type: str = Field(default="USER", pattern="^(USER|SERVICE|SHARED|BREAK_GLASS|EXTERNAL)$")
    privilege_level: str = Field(default="STANDARD", pattern="^(STANDARD|PRIVILEGED|GLOBAL_ADMIN|EMERGENCY)$")
    status: str = Field(default="ACTIVE", pattern="^(ACTIVE|DISABLED|PENDING_REVIEW|TERMINATED)$")
    owner: str | None = Field(default=None, max_length=200)
    mfa_status: str = Field(default="UNKNOWN", pattern="^(ENFORCED|EXCLUDED|NOT_ENROLLED|UNKNOWN|NOT_APPLICABLE)$")
    last_reviewed_at: datetime | None = None
    evidence_reference: str | None = Field(default=None, max_length=5000)


class InventoryAssetRequest(BaseModel):
    asset_type: str = Field(pattern="^(SOFTWARE|HARDWARE)$")
    asset_identifier: str = Field(min_length=2, max_length=240)
    name: str = Field(min_length=2, max_length=240)
    publisher_or_manufacturer: str | None = Field(default=None, max_length=240)
    version_or_model: str | None = Field(default=None, max_length=240)
    owner: str | None = Field(default=None, max_length=200)
    system_role: str | None = Field(default=None, max_length=240)
    authorization_status: str = Field(default="PENDING_REVIEW", pattern="^(AUTHORIZED|PENDING_REVIEW|RESTRICTED|RETIRED)$")
    cui_in_scope: bool = False
    lifecycle_status: str = Field(default="ACTIVE", pattern="^(ACTIVE|MAINTENANCE|RETIRED|DISPOSED)$")
    last_reviewed_at: datetime | None = None
    evidence_reference: str | None = Field(default=None, max_length=5000)
    notes: str | None = Field(default=None, max_length=5000)


class ChangeRecordRequest(BaseModel):
    title: str = Field(min_length=3, max_length=240)
    description: str | None = Field(default=None, max_length=5000)
    change_type: str = Field(default="STANDARD", pattern="^(STANDARD|NORMAL|EMERGENCY)$")
    risk_level: str = Field(default="MEDIUM", pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    status: str = Field(default="DRAFT", pattern="^(DRAFT|SUBMITTED|APPROVED|SCHEDULED|IMPLEMENTING|CLOSED|REJECTED|CANCELLED)$")
    owner: str | None = Field(default=None, max_length=200)
    approver: str | None = Field(default=None, max_length=200)
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None
    rollback_plan: str | None = Field(default=None, max_length=5000)
    evidence_reference: str | None = Field(default=None, max_length=5000)
    asset_id: str | None = Field(default=None, max_length=36)
    poam_item_id: str | None = Field(default=None, max_length=36)


def finding_out(finding: Finding) -> dict:
    objective = finding.framework_objective or finding.objective
    evidence = finding.evidence[-1].payload if finding.evidence else {}
    return {"id": finding.id, "objective": objective.identifier, "status": finding.status, "detail": finding.detail, "evidenceCount": len(finding.evidence), "reviewFlags": evidence.get("reviewFlags", [])}


def audit_review_out(review: AuditEvidenceReview) -> dict:
    return {"retentionDays": review.retention_days, "reviewOwner": review.review_owner, "reviewFrequency": review.review_frequency, "requiredEventCategories": review.required_event_categories, "status": review.status, "notes": review.notes, "updatedAt": review.updated_at}


def poam_out(item: PoamItem) -> dict:
    objective = item.objective_link.objective_identifier if item.objective_link else None
    if item.finding:
        linked_objective = item.finding.framework_objective or item.finding.objective
        objective = linked_objective.identifier
    return {"id": item.id, "findingId": item.finding_id, "objective": objective, "title": item.title, "description": item.description, "owner": item.owner, "status": item.status, "targetDate": item.target_date, "milestones": item.milestones, "evidenceReference": item.evidence_reference, "createdAt": item.created_at, "updatedAt": item.updated_at}


def exception_out(item: PolicyException) -> dict:
    return {"id": item.id, "objectiveIdentifier": item.objective_identifier, "title": item.title, "rationale": item.rationale, "compensatingControls": item.compensating_controls, "owner": item.owner, "status": item.status, "expiresAt": item.expires_at, "reviewedBy": item.reviewed_by, "createdAt": item.created_at, "updatedAt": item.updated_at}


def account_out(item: ManagedAccount) -> dict:
    return {"id": item.id, "accountIdentifier": item.account_identifier, "displayName": item.display_name, "accountType": item.account_type, "privilegeLevel": item.privilege_level, "status": item.status, "owner": item.owner, "mfaStatus": item.mfa_status, "lastReviewedAt": item.last_reviewed_at, "source": item.source, "sourceId": item.source_id, "lastSyncedAt": item.last_synced_at, "evidenceReference": item.evidence_reference, "createdAt": item.created_at, "updatedAt": item.updated_at}


def asset_out(item: InventoryAsset) -> dict:
    return {"id": item.id, "assetType": item.asset_type, "assetIdentifier": item.asset_identifier, "name": item.name, "publisherOrManufacturer": item.publisher_or_manufacturer, "versionOrModel": item.version_or_model, "owner": item.owner, "systemRole": item.system_role, "authorizationStatus": item.authorization_status, "cuiInScope": item.cui_in_scope, "lifecycleStatus": item.lifecycle_status, "lastReviewedAt": item.last_reviewed_at, "source": item.source, "sourceId": item.source_id, "lastSyncedAt": item.last_synced_at, "evidenceReference": item.evidence_reference, "notes": item.notes, "createdAt": item.created_at, "updatedAt": item.updated_at}


def change_out(item: ChangeRecord) -> dict:
    return {"id": item.id, "title": item.title, "description": item.description, "changeType": item.change_type, "riskLevel": item.risk_level, "status": item.status, "owner": item.owner, "approver": item.approver, "plannedStartAt": item.planned_start_at, "plannedEndAt": item.planned_end_at, "rollbackPlan": item.rollback_plan, "evidenceReference": item.evidence_reference, "assetId": item.asset_id, "assetName": item.asset.name if item.asset else None, "poamItemId": item.poam_item_id, "poamTitle": item.poam_item.title if item.poam_item else None, "createdAt": item.created_at, "updatedAt": item.updated_at}


def screenshot_out(item: ScreenshotEvidence) -> dict:
    return {"id": item.id, "title": item.title, "objectiveIdentifier": item.objective_identifier, "relatedRecordType": item.related_record_type, "relatedRecordId": item.related_record_id, "capturedBy": item.captured_by, "containsCui": item.contains_cui, "notes": item.notes, "source": item.source, "contentType": item.content_type, "byteSize": item.byte_size, "sha256": item.sha256, "capturedAt": item.captured_at}


def run_out(run: AssessmentRun) -> dict:
    findings = run.findings
    statuses = {item.status for item in findings}
    overall = "NON_COMPLIANT" if "NON_COMPLIANT" in statuses else "MANUAL_REVIEW" if "MANUAL_REVIEW" in statuses else "COMPLIANT" if "COMPLIANT" in statuses else "NOT_RUN"
    return {"id": run.id, "tenantId": run.tenant_id, "frameworkVersion": run.framework_release.version if run.framework_release else None, "startedAt": run.started_at, "finishedAt": run.finished_at, "overallStatus": overall, "findingCount": len(findings), "manualReviewCount": sum(item.status == "MANUAL_REVIEW" for item in findings), "nonCompliantCount": sum(item.status == "NON_COMPLIANT" for item in findings)}


def active_framework_release(session: Session) -> FrameworkRelease | None:
    return session.scalar(select(FrameworkRelease).where(FrameworkRelease.framework == "CMMC", FrameworkRelease.level == 2, FrameworkRelease.status.in_(["SOURCE_VALIDATED", "VERIFIED"])).order_by(FrameworkRelease.imported_at.desc()))


@app.get("/healthz")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/catalog/summary")
def catalog_summary(session: Session = Depends(get_session)) -> dict:
    release = active_framework_release(session)
    placemat = session.scalar(select(MicrosoftPlacematRelease).order_by(MicrosoftPlacematRelease.imported_at.desc()))
    practice_count = session.query(FrameworkPractice).filter(FrameworkPractice.release_id == release.id).count() if release else session.query(AssessmentObjective.practice_id).distinct().count()
    objective_count = session.query(FrameworkAssessmentObjective).join(FrameworkPractice).filter(FrameworkPractice.release_id == release.id).count() if release else session.query(AssessmentObjective).count()
    return {"practices": practice_count, "objectives": objective_count, "rules": len(AUTOMATED_CHECKS), "framework": {"status": release.status if release else "UNVERIFIED_SEED", "version": release.version if release else None, "sourceUrl": release.source_url if release else None}, "microsoftPlacemat": {"status": placemat.status if placemat else "NOT_IMPORTED", "version": placemat.version_label if placemat else None, "mappings": len(placemat.mappings) if placemat else 0}}


@app.get("/api/dashboard/overview")
def dashboard_overview(session: Session = Depends(get_session)) -> dict:
    status_counts = dict(session.execute(select(Finding.status, func.count()).group_by(Finding.status)).all())
    latest_runs = session.scalars(select(AssessmentRun).options(selectinload(AssessmentRun.findings), selectinload(AssessmentRun.framework_release)).order_by(AssessmentRun.started_at.desc()).limit(5)).all()
    return {"findings": {"compliant": status_counts.get("COMPLIANT", 0), "manualReview": status_counts.get("MANUAL_REVIEW", 0), "nonCompliant": status_counts.get("NON_COMPLIANT", 0)}, "assessmentCount": session.scalar(select(func.count()).select_from(AssessmentRun)) or 0, "recentRuns": [run_out(run) for run in latest_runs]}


@app.get("/api/assessments")
def list_assessments(session: Session = Depends(get_session)) -> dict:
    runs = session.scalars(select(AssessmentRun).options(selectinload(AssessmentRun.findings), selectinload(AssessmentRun.framework_release)).order_by(AssessmentRun.started_at.desc()).limit(100)).all()
    return {"items": [run_out(run) for run in runs]}


@app.get("/api/evidence")
def list_evidence(session: Session = Depends(get_session)) -> dict:
    items = session.scalars(select(EvidenceLog).options(selectinload(EvidenceLog.finding).selectinload(Finding.framework_objective), selectinload(EvidenceLog.finding).selectinload(Finding.objective), selectinload(EvidenceLog.finding).selectinload(Finding.run)).order_by(EvidenceLog.captured_at.desc()).limit(200)).all()
    return {"items": [{"id": item.id, "runId": item.finding.run_id, "objective": (item.finding.framework_objective or item.finding.objective).identifier, "source": item.source, "capturedAt": item.captured_at, "status": item.finding.status, "payloadHash": item.payload_hash, "chainHash": item.chain_hash} for item in items]}


@app.get("/api/screenshots")
def list_screenshots(session: Session = Depends(get_session)) -> dict:
    items = session.scalars(select(ScreenshotEvidence).order_by(ScreenshotEvidence.captured_at.desc()).limit(200)).all()
    return {"items": [screenshot_out(item) for item in items]}


@app.post("/api/screenshots", status_code=status.HTTP_201_CREATED)
async def upload_screenshot(request: Request, title: str = "", objective_identifier: str | None = None, related_record_type: str | None = None, related_record_id: str | None = None, captured_by: str | None = None, contains_cui: bool = False, notes: str | None = None, session: Session = Depends(get_session)) -> dict:
    normalized_title = title.strip()
    if len(normalized_title) < 3 or len(normalized_title) > 240:
        raise HTTPException(422, "Screenshot title must be between 3 and 240 characters.")
    content_type = (request.headers.get("content-type") or "").split(";", 1)[0].lower()
    if content_type not in {"image/png", "image/jpeg"}:
        raise HTTPException(415, "Only PNG and JPEG screenshots are accepted.")
    image_data = await read_image(request, content_type)
    if related_record_type and related_record_type not in {"ASSESSMENT", "ACCOUNT", "ASSET", "CHANGE", "POAM", "POLICY_EXCEPTION"}:
        raise HTTPException(422, "Unsupported related record type.")
    item = ScreenshotEvidence(title=normalized_title, objective_identifier=objective_identifier.strip() if objective_identifier else None, related_record_type=related_record_type, related_record_id=related_record_id.strip() if related_record_id else None, captured_by=get_settings().app_username, contains_cui=contains_cui, notes=notes.strip() if notes else None, content_type=content_type, byte_size=len(image_data), sha256=hashlib.sha256(image_data).hexdigest(), image_data=image_data)
    session.add(item)
    session.commit()
    session.refresh(item)
    return screenshot_out(item)


@app.get("/api/screenshots/{item_id}/content")
def screenshot_content(item_id: str, session: Session = Depends(get_session)) -> Response:
    item = session.get(ScreenshotEvidence, item_id)
    if not item:
        raise HTTPException(404, "Screenshot evidence not found.")
    extension = "png" if item.content_type == "image/png" else "jpg"
    return Response(item.image_data, media_type=item.content_type, headers={"Content-Disposition": f'inline; filename="evidence-screenshot-{item.id}.{extension}"', "X-Content-Type-Options": "nosniff"})


@app.get("/api/poam")
def list_poam(session: Session = Depends(get_session)) -> dict:
    items = session.scalars(select(PoamItem).options(selectinload(PoamItem.finding).selectinload(Finding.framework_objective), selectinload(PoamItem.finding).selectinload(Finding.objective)).order_by(PoamItem.updated_at.desc()).limit(100)).all()
    plans = session.scalars(select(RemediationPlan).options(selectinload(RemediationPlan.approvals), selectinload(RemediationPlan.finding).selectinload(Finding.framework_objective), selectinload(RemediationPlan.finding).selectinload(Finding.objective)).order_by(RemediationPlan.expires_at.desc()).limit(100)).all()
    return {"items": [poam_out(item) for item in items], "remediationPlans": [{"id": plan.id, "objective": (plan.finding.framework_objective or plan.finding.objective).identifier, "state": plan.state, "expiresAt": plan.expires_at, "approvalCount": len(plan.approvals)} for plan in plans]}


@app.post("/api/poam", status_code=status.HTTP_201_CREATED)
def create_poam_item(body: PoamItemRequest, session: Session = Depends(get_session)) -> dict:
    if body.finding_id and not session.get(Finding, body.finding_id):
        raise HTTPException(404, "The linked finding was not found.")
    item = PoamItem(
        finding_id=body.finding_id,
        title=body.title.strip(),
        description=body.description.strip() if body.description else None,
        owner=body.owner.strip() if body.owner else None,
        status=body.status,
        target_date=body.target_date,
        milestones=[milestone.strip() for milestone in body.milestones if milestone.strip()],
        evidence_reference=body.evidence_reference.strip() if body.evidence_reference else None,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return poam_out(item)


@app.patch("/api/poam/{item_id}")
def update_poam_item(item_id: str, body: PoamItemRequest, session: Session = Depends(get_session)) -> dict:
    item = session.get(PoamItem, item_id)
    if not item:
        raise HTTPException(404, "POA&M item not found.")
    if body.finding_id and not session.get(Finding, body.finding_id):
        raise HTTPException(404, "The linked finding was not found.")
    item.finding_id = body.finding_id
    item.title = body.title.strip()
    item.description = body.description.strip() if body.description else None
    item.owner = body.owner.strip() if body.owner else None
    item.status = body.status
    item.target_date = body.target_date
    item.milestones = [milestone.strip() for milestone in body.milestones if milestone.strip()]
    item.evidence_reference = body.evidence_reference.strip() if body.evidence_reference else None
    session.commit()
    session.refresh(item)
    return poam_out(item)


@app.get("/api/exceptions")
def list_policy_exceptions(session: Session = Depends(get_session)) -> dict:
    items = session.scalars(select(PolicyException).order_by(PolicyException.updated_at.desc()).limit(100)).all()
    return {"items": [exception_out(item) for item in items]}


@app.post("/api/exceptions", status_code=status.HTTP_201_CREATED)
def create_policy_exception(body: PolicyExceptionRequest, session: Session = Depends(get_session)) -> dict:
    item = PolicyException(
        objective_identifier=body.objective_identifier.strip() if body.objective_identifier else None,
        title=body.title.strip(),
        rationale=body.rationale.strip(),
        compensating_controls=body.compensating_controls.strip() if body.compensating_controls else None,
        owner=body.owner.strip() if body.owner else None,
        status=body.status,
        expires_at=body.expires_at,
        reviewed_by=body.reviewed_by.strip() if body.reviewed_by else None,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return exception_out(item)


@app.patch("/api/exceptions/{item_id}")
def update_policy_exception(item_id: str, body: PolicyExceptionRequest, session: Session = Depends(get_session)) -> dict:
    item = session.get(PolicyException, item_id)
    if not item:
        raise HTTPException(404, "Policy exception not found.")
    item.objective_identifier = body.objective_identifier.strip() if body.objective_identifier else None
    item.title = body.title.strip()
    item.rationale = body.rationale.strip()
    item.compensating_controls = body.compensating_controls.strip() if body.compensating_controls else None
    item.owner = body.owner.strip() if body.owner else None
    item.status = body.status
    item.expires_at = body.expires_at
    item.reviewed_by = body.reviewed_by.strip() if body.reviewed_by else None
    session.commit()
    session.refresh(item)
    return exception_out(item)


@app.get("/api/accounts")
def list_accounts(session: Session = Depends(get_session)) -> dict:
    items = session.scalars(select(ManagedAccount).order_by(ManagedAccount.updated_at.desc()).limit(500)).all()
    return {"items": [account_out(item) for item in items]}


def apply_account(item: ManagedAccount, body: ManagedAccountRequest) -> None:
    item.account_identifier = body.account_identifier.strip()
    item.display_name = body.display_name.strip() if body.display_name else None
    item.account_type = body.account_type
    item.privilege_level = body.privilege_level
    item.status = body.status
    item.owner = body.owner.strip() if body.owner else None
    item.mfa_status = body.mfa_status
    item.last_reviewed_at = body.last_reviewed_at
    item.evidence_reference = body.evidence_reference.strip() if body.evidence_reference else None


@app.post("/api/accounts", status_code=status.HTTP_201_CREATED)
def create_account(body: ManagedAccountRequest, session: Session = Depends(get_session)) -> dict:
    identifier = body.account_identifier.strip()
    if session.scalar(select(ManagedAccount).where(ManagedAccount.account_identifier == identifier)):
        raise HTTPException(409, "An account with this identifier already exists.")
    item = ManagedAccount(account_identifier=identifier)
    apply_account(item, body)
    session.add(item)
    session.commit()
    session.refresh(item)
    return account_out(item)


@app.patch("/api/accounts/{item_id}")
def update_account(item_id: str, body: ManagedAccountRequest, session: Session = Depends(get_session)) -> dict:
    item = session.get(ManagedAccount, item_id)
    if not item:
        raise HTTPException(404, "Account record not found.")
    existing = session.scalar(select(ManagedAccount).where(ManagedAccount.account_identifier == body.account_identifier.strip(), ManagedAccount.id != item_id))
    if existing:
        raise HTTPException(409, "An account with this identifier already exists.")
    apply_account(item, body)
    session.commit()
    session.refresh(item)
    return account_out(item)


@app.get("/api/inventory")
def list_inventory(asset_type: str | None = None, session: Session = Depends(get_session)) -> dict:
    statement = select(InventoryAsset).order_by(InventoryAsset.updated_at.desc()).limit(500)
    if asset_type:
        normalized = asset_type.upper()
        if normalized not in {"SOFTWARE", "HARDWARE"}:
            raise HTTPException(422, "asset_type must be SOFTWARE or HARDWARE.")
        statement = statement.where(InventoryAsset.asset_type == normalized)
    items = session.scalars(statement).all()
    return {"items": [asset_out(item) for item in items]}


def apply_asset(item: InventoryAsset, body: InventoryAssetRequest) -> None:
    item.asset_type = body.asset_type
    item.asset_identifier = body.asset_identifier.strip()
    item.name = body.name.strip()
    item.publisher_or_manufacturer = body.publisher_or_manufacturer.strip() if body.publisher_or_manufacturer else None
    item.version_or_model = body.version_or_model.strip() if body.version_or_model else None
    item.owner = body.owner.strip() if body.owner else None
    item.system_role = body.system_role.strip() if body.system_role else None
    item.authorization_status = body.authorization_status
    item.cui_in_scope = body.cui_in_scope
    item.lifecycle_status = body.lifecycle_status
    item.last_reviewed_at = body.last_reviewed_at
    item.evidence_reference = body.evidence_reference.strip() if body.evidence_reference else None
    item.notes = body.notes.strip() if body.notes else None


@app.post("/api/inventory", status_code=status.HTTP_201_CREATED)
def create_inventory_asset(body: InventoryAssetRequest, session: Session = Depends(get_session)) -> dict:
    asset_type, identifier = body.asset_type, body.asset_identifier.strip()
    if session.scalar(select(InventoryAsset).where(InventoryAsset.asset_type == asset_type, InventoryAsset.asset_identifier == identifier)):
        raise HTTPException(409, "An asset with this type and identifier already exists.")
    item = InventoryAsset(asset_type=asset_type, asset_identifier=identifier, name=body.name.strip())
    apply_asset(item, body)
    session.add(item)
    session.commit()
    session.refresh(item)
    return asset_out(item)


@app.patch("/api/inventory/{item_id}")
def update_inventory_asset(item_id: str, body: InventoryAssetRequest, session: Session = Depends(get_session)) -> dict:
    item = session.get(InventoryAsset, item_id)
    if not item:
        raise HTTPException(404, "Inventory record not found.")
    existing = session.scalar(select(InventoryAsset).where(InventoryAsset.asset_type == body.asset_type, InventoryAsset.asset_identifier == body.asset_identifier.strip(), InventoryAsset.id != item_id))
    if existing:
        raise HTTPException(409, "An asset with this type and identifier already exists.")
    apply_asset(item, body)
    session.commit()
    session.refresh(item)
    return asset_out(item)


@app.get("/api/changes")
def list_changes(session: Session = Depends(get_session)) -> dict:
    items = session.scalars(select(ChangeRecord).options(selectinload(ChangeRecord.asset), selectinload(ChangeRecord.poam_item)).order_by(ChangeRecord.updated_at.desc()).limit(500)).all()
    return {"items": [change_out(item) for item in items]}


def apply_change(item: ChangeRecord, body: ChangeRecordRequest, session: Session) -> None:
    if body.asset_id and not session.get(InventoryAsset, body.asset_id):
        raise HTTPException(404, "The linked inventory asset was not found.")
    if body.poam_item_id and not session.get(PoamItem, body.poam_item_id):
        raise HTTPException(404, "The linked POA&M item was not found.")
    item.title = body.title.strip()
    item.description = body.description.strip() if body.description else None
    item.change_type = body.change_type
    item.risk_level = body.risk_level
    item.status = body.status
    item.owner = body.owner.strip() if body.owner else None
    item.approver = body.approver.strip() if body.approver else None
    item.planned_start_at = body.planned_start_at
    item.planned_end_at = body.planned_end_at
    item.rollback_plan = body.rollback_plan.strip() if body.rollback_plan else None
    item.evidence_reference = body.evidence_reference.strip() if body.evidence_reference else None
    item.asset_id = body.asset_id
    item.poam_item_id = body.poam_item_id


@app.post("/api/changes", status_code=status.HTTP_201_CREATED)
def create_change(body: ChangeRecordRequest, session: Session = Depends(get_session)) -> dict:
    item = ChangeRecord(title=body.title.strip())
    apply_change(item, body, session)
    session.add(item)
    session.commit()
    session.refresh(item)
    return change_out(item)


@app.patch("/api/changes/{item_id}")
def update_change(item_id: str, body: ChangeRecordRequest, session: Session = Depends(get_session)) -> dict:
    item = session.get(ChangeRecord, item_id)
    if not item:
        raise HTTPException(404, "Change record not found.")
    apply_change(item, body, session)
    session.commit()
    session.refresh(item)
    return change_out(item)


def graph_sync_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(403, str(exc))
    return HTTPException(502, f"Read-only Microsoft Graph sync could not complete: {exc}")


@app.post("/api/sync/accounts")
async def sync_accounts_from_tenant(session: Session = Depends(get_session)) -> dict:
    client = GraphClient()
    try:
        users = await client.get_collection("/users?$select=id,userPrincipalName,displayName,userType,accountEnabled&$top=999", "User.Read.All")
    except (PermissionError, RuntimeError, httpx.HTTPError) as exc:
        raise graph_sync_error(exc) from exc

    role_assignments: dict[str, str] = {}
    warnings: list[str] = []
    try:
        roles = await client.get_collection("/directoryRoles?$select=id,displayName", "RoleManagement.Read.Directory")
        for role in roles:
            members = await client.get_collection(f"/directoryRoles/{role['id']}/members?$select=id", "RoleManagement.Read.Directory")
            privilege = "GLOBAL_ADMIN" if role.get("displayName") == "Global Administrator" else "PRIVILEGED"
            for member in members:
                member_id = member.get("id")
                if member_id:
                    role_assignments[str(member_id)] = "GLOBAL_ADMIN" if privilege == "GLOBAL_ADMIN" else role_assignments.get(str(member_id), privilege)
    except (PermissionError, RuntimeError, httpx.HTTPError) as exc:
        warnings.append(f"Privileged-role membership was not refreshed: {exc}")

    synced_at = datetime.now(UTC).replace(tzinfo=None)
    created = updated = 0
    for user in users:
        source_id = str(user.get("id") or "")
        if not source_id:
            continue
        identifier = str(user.get("userPrincipalName") or source_id)
        item = session.scalar(select(ManagedAccount).where(ManagedAccount.source_id == source_id))
        if not item:
            item = session.scalar(select(ManagedAccount).where(ManagedAccount.account_identifier == identifier))
        is_new = item is None
        if is_new:
            item = ManagedAccount(account_identifier=identifier)
            session.add(item)
            created += 1
        else:
            updated += 1
        item.account_identifier = identifier
        item.display_name = user.get("displayName") or None
        item.account_type = "EXTERNAL" if str(user.get("userType") or "").upper() == "GUEST" else "USER"
        item.privilege_level = role_assignments.get(source_id, "STANDARD")
        item.status = "ACTIVE" if user.get("accountEnabled") is not False else "DISABLED"
        item.source = "Microsoft Graph /users"
        item.source_id = source_id
        item.last_synced_at = synced_at
    session.commit()
    return {"source": "Microsoft Graph /users", "syncedAt": synced_at, "created": created, "updated": updated, "total": created + updated, "warnings": warnings, "manualReview": "MFA registration and privileged-access paths remain assessor-review fields."}


def upsert_synced_asset(session: Session, *, asset_type: str, source: str, source_id: str, asset_identifier: str, name: str, publisher_or_manufacturer: str | None, version_or_model: str | None, owner: str | None, system_role: str | None, synced_at: datetime) -> bool:
    item = session.scalar(select(InventoryAsset).where(InventoryAsset.source_id == source_id))
    if not item:
        item = session.scalar(select(InventoryAsset).where(InventoryAsset.asset_type == asset_type, InventoryAsset.asset_identifier == asset_identifier))
    is_new = item is None
    if is_new:
        item = InventoryAsset(asset_type=asset_type, asset_identifier=asset_identifier, name=name)
        session.add(item)
    item.asset_type = asset_type
    item.asset_identifier = asset_identifier
    item.name = name
    item.publisher_or_manufacturer = publisher_or_manufacturer
    item.version_or_model = version_or_model
    if owner:
        item.owner = owner
    item.system_role = system_role
    item.source = source
    item.source_id = source_id
    item.last_synced_at = synced_at
    return is_new


@app.post("/api/sync/inventory")
async def sync_inventory_from_tenant(session: Session = Depends(get_session)) -> dict:
    client = GraphClient()
    try:
        devices = await client.get_collection("/deviceManagement/managedDevices?$select=id,deviceName,serialNumber,manufacturer,model,operatingSystem,osVersion,userPrincipalName,lastSyncDateTime&$top=999", "DeviceManagementManagedDevices.Read.All")
        detected_apps = await client.get_collection("/deviceManagement/detectedApps?$select=id,displayName,version,publisher,platform,deviceCount&$top=999", "DeviceManagementManagedDevices.Read.All")
    except (PermissionError, RuntimeError, httpx.HTTPError) as exc:
        raise graph_sync_error(exc) from exc

    warnings: list[str] = []
    try:
        managed_apps = await client.get_collection("/deviceAppManagement/mobileApps?$select=id,displayName,publisher&$top=999", "DeviceManagementApps.Read.All")
    except (PermissionError, RuntimeError, httpx.HTTPError) as exc:
        managed_apps = []
        warnings.append(f"The Intune managed-app catalog was not refreshed: {exc}")

    synced_at = datetime.now(UTC).replace(tzinfo=None)
    counts = {"hardware": {"created": 0, "updated": 0}, "software": {"created": 0, "updated": 0}}
    for device in devices:
        source_id = str(device.get("id") or "")
        if not source_id:
            continue
        created = upsert_synced_asset(session, asset_type="HARDWARE", source="Microsoft Graph /deviceManagement/managedDevices", source_id=source_id, asset_identifier=f"intune-device:{source_id}", name=str(device.get("deviceName") or source_id), publisher_or_manufacturer=device.get("manufacturer") or None, version_or_model=device.get("model") or None, owner=device.get("userPrincipalName") or None, system_role=" · ".join(part for part in (device.get("operatingSystem"), device.get("osVersion")) if part) or None, synced_at=synced_at)
        counts["hardware"]["created" if created else "updated"] += 1
    for app in detected_apps:
        source_id = str(app.get("id") or "")
        if not source_id:
            continue
        created = upsert_synced_asset(session, asset_type="SOFTWARE", source="Microsoft Graph /deviceManagement/detectedApps", source_id=f"detected:{source_id}", asset_identifier=f"intune-detected-app:{source_id}", name=str(app.get("displayName") or source_id), publisher_or_manufacturer=app.get("publisher") or None, version_or_model=" · ".join(part for part in (app.get("version"), app.get("platform")) if part) or None, owner=None, system_role=f"Detected on {app.get('deviceCount', 0)} managed devices", synced_at=synced_at)
        counts["software"]["created" if created else "updated"] += 1
    for app in managed_apps:
        source_id = str(app.get("id") or "")
        if not source_id:
            continue
        created = upsert_synced_asset(session, asset_type="SOFTWARE", source="Microsoft Graph /deviceAppManagement/mobileApps", source_id=f"managed:{source_id}", asset_identifier=f"intune-managed-app:{source_id}", name=str(app.get("displayName") or source_id), publisher_or_manufacturer=app.get("publisher") or None, version_or_model=None, owner=None, system_role="Intune managed app catalog", synced_at=synced_at)
        counts["software"]["created" if created else "updated"] += 1
    session.commit()
    return {"source": "Microsoft Graph Intune", "syncedAt": synced_at, "devicesRead": len(devices), "detectedAppsRead": len(detected_apps), "managedAppsRead": len(managed_apps), "counts": counts, "warnings": warnings, "manualReview": "CUI scope and authorization status remain assessor-review fields; sync does not set either automatically."}


@app.post("/api/assessments", status_code=status.HTTP_201_CREATED)
async def start_assessment(body: RunRequest, session: Session = Depends(get_session)) -> dict:
    release = active_framework_release(session)
    if not release:
        raise HTTPException(409, "A source-validated CMMC Level 2 catalog must be imported before starting an assessment.")
    run = AssessmentRun(tenant_id=body.tenant_id, framework_release_id=release.id)
    session.add(run)
    session.flush()
    client = GraphClient()
    findings = []
    for check, source in AUTOMATED_CHECKS:
        result = await check(client)
        objective = session.scalar(select(AssessmentObjective).where(AssessmentObjective.identifier == result.evaluated_objective))
        framework_objective = session.scalar(select(FrameworkAssessmentObjective).join(FrameworkPractice).where(FrameworkPractice.release_id == release.id, FrameworkAssessmentObjective.identifier == result.evaluated_objective))
        if not objective or not framework_objective:
            raise HTTPException(500, "Assessment objective is missing from the active catalog.")
        finding = Finding(run_id=run.id, objective_id=objective.id, framework_objective_id=framework_objective.id, status=result.status, detail=result.detail)
        session.add(finding)
        session.flush()
        previous = session.scalar(select(EvidenceLog.chain_hash).order_by(EvidenceLog.captured_at.desc()))
        payload_hash, chain_hash = _canonical_hash(result.evidence, previous)
        session.add(EvidenceLog(finding_id=finding.id, source=source, payload=result.evidence, payload_hash=payload_hash, previous_hash=previous, chain_hash=chain_hash))
        findings.append(finding)
    audit_review = AuditEvidenceReview(run=run)
    session.add(audit_review)
    run.finished_at = datetime.utcnow()
    session.commit()
    for finding in findings:
        session.refresh(finding)
    return {"runId": run.id, "finding": finding_out(findings[0]), "findings": [finding_out(finding) for finding in findings], "auditReview": audit_review_out(audit_review)}


@app.get("/api/assessments/{run_id}")
def get_assessment(run_id: str, session: Session = Depends(get_session)) -> dict:
    run = session.get(AssessmentRun, run_id)
    if not run:
        raise HTTPException(404, "Assessment run not found")
    findings = session.scalars(select(Finding).where(Finding.run_id == run_id)).all()
    return {"id": run.id, "tenantId": run.tenant_id, "framework": {"version": run.framework_release.version, "status": run.framework_release.status} if run.framework_release else None, "startedAt": run.started_at, "finishedAt": run.finished_at, "findings": [finding_out(item) for item in findings], "auditReview": audit_review_out(run.audit_review) if run.audit_review else None}


@app.get("/api/assessments/{run_id}/audit-review")
def get_audit_review(run_id: str, session: Session = Depends(get_session)) -> dict:
    review = session.scalar(select(AuditEvidenceReview).where(AuditEvidenceReview.run_id == run_id))
    if not review:
        raise HTTPException(404, "Audit review is unavailable for this assessment run.")
    return audit_review_out(review)


@app.put("/api/assessments/{run_id}/audit-review")
def save_audit_review(run_id: str, body: AuditReviewRequest, session: Session = Depends(get_session)) -> dict:
    review = session.scalar(select(AuditEvidenceReview).where(AuditEvidenceReview.run_id == run_id))
    if not review:
        raise HTTPException(404, "Audit review is unavailable for this assessment run.")
    review.retention_days = body.retention_days
    review.review_owner = body.review_owner
    review.review_frequency = body.review_frequency
    review.required_event_categories = [item.strip() for item in body.required_event_categories if item.strip()]
    review.status = body.status
    review.notes = body.notes
    session.commit()
    session.refresh(review)
    return audit_review_out(review)


@app.get("/api/assessments/{run_id}/ssp.md")
def download_ssp(run_id: str, session: Session = Depends(get_session)) -> Response:
    try:
        content = ssp_markdown(session, run_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(content, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="ssp-{run_id}.md"'})


@app.get("/api/assessments/{run_id}/evidence.json")
def download_evidence(run_id: str, session: Session = Depends(get_session)) -> Response:
    return Response(content=json.dumps(evidence_json(session, run_id), indent=2), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="evidence-{run_id}.json"'})


@app.post("/api/findings/{finding_id}/remediation-plans", status_code=status.HTTP_201_CREATED)
def propose_remediation(finding_id: str, session: Session = Depends(get_session)) -> dict:
    finding = session.get(Finding, finding_id)
    if not finding or finding.status != "NON_COMPLIANT":
        raise HTTPException(409, "A non-compliant finding is required to propose remediation")
    rule = session.scalar(select(TenantCheckRule).where(TenantCheckRule.objective_id == finding.objective_id, TenantCheckRule.enabled.is_(True)))
    if not rule:
        raise HTTPException(404, "No approved remediation rule is associated with this finding")
    try:
        request = build_remediation_request({"remediation": rule.remediation})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    plan = RemediationPlan(finding_id=finding_id, request=request, expires_at=expiry())
    session.add(plan)
    session.commit()
    return {"planId": plan.id, "state": plan.state, "expiresAt": plan.expires_at, "request": plan.request}


@app.post("/api/remediation-plans/{plan_id}/approvals")
def approve_remediation(plan_id: str, body: ApprovalRequest, x_approval_signature: str = Header(default=""), session: Session = Depends(get_session)) -> dict:
    settings = get_settings()
    expected = hashlib.sha256(f"{plan_id}:{body.approver_id}:{settings.approval_webhook_shared_secret}".encode()).hexdigest()
    if not settings.approval_webhook_shared_secret or not x_approval_signature or not hmac.compare_digest(x_approval_signature, expected):
        raise HTTPException(401, "Approval webhook signature is required")
    if not body.mfa_confirmed:
        raise HTTPException(422, "MFA-confirmed approval is required")
    plan = session.get(RemediationPlan, plan_id)
    if not plan or plan.expires_at <= datetime.utcnow():
        raise HTTPException(410, "Plan was not found or its approval window has expired")
    if any(item.approver_id == body.approver_id for item in plan.approvals):
        raise HTTPException(409, "This approver has already approved the plan")
    session.add(RemediationApproval(plan_id=plan.id, approver_id=body.approver_id, mfa_confirmed=True))
    session.flush()
    count = len(plan.approvals)
    if count >= 2:
        plan.state = "APPROVED"
    session.commit()
    return {"planId": plan.id, "state": plan.state, "approvalCount": count, "executionEligible": execution_allowed(plan, count)}

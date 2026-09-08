import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def uid() -> str:
    return str(uuid.uuid4())


class Domain(Base):
    __tablename__ = "domains"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(4), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    practices: Mapped[list["Practice"]] = relationship(back_populates="domain", cascade="all, delete-orphan")


class FrameworkRelease(Base):
    """A source-traceable framework baseline, independent of tenant evidence."""
    __tablename__ = "framework_releases"
    __table_args__ = (UniqueConstraint("framework", "level", "version", name="uq_framework_release"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    framework: Mapped[str] = mapped_column(String(80), index=True)
    level: Mapped[int] = mapped_column(Integer)
    version: Mapped[str] = mapped_column(String(40))
    source_url: Mapped[str] = mapped_column(String(1000))
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    imported_by: Mapped[str] = mapped_column(String(200), default="system")
    practices: Mapped[list["FrameworkPractice"]] = relationship(back_populates="release", cascade="all, delete-orphan")


class FrameworkPractice(Base):
    __tablename__ = "framework_practices"
    __table_args__ = (UniqueConstraint("release_id", "identifier", name="uq_framework_practice"), Index("ix_framework_practice_identifier", "identifier"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    release_id: Mapped[str] = mapped_column(ForeignKey("framework_releases.id"), index=True)
    domain_code: Mapped[str] = mapped_column(String(4), index=True)
    identifier: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(Text)
    statement: Mapped[str] = mapped_column(Text)
    release: Mapped[FrameworkRelease] = relationship(back_populates="practices")
    objectives: Mapped[list["FrameworkAssessmentObjective"]] = relationship(back_populates="practice", cascade="all, delete-orphan")


class FrameworkAssessmentObjective(Base):
    __tablename__ = "framework_assessment_objectives"
    __table_args__ = (UniqueConstraint("practice_id", "identifier", name="uq_framework_objective"), Index("ix_framework_objective_identifier", "identifier"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    practice_id: Mapped[str] = mapped_column(ForeignKey("framework_practices.id"), index=True)
    identifier: Mapped[str] = mapped_column(String(40), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    statement: Mapped[str] = mapped_column(Text)
    practice: Mapped[FrameworkPractice] = relationship(back_populates="objectives")


class MicrosoftPlacematRelease(Base):
    __tablename__ = "microsoft_placemat_releases"
    __table_args__ = (UniqueConstraint("source_sha256", name="uq_placemat_source_hash"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(255))
    version_label: Mapped[str] = mapped_column(String(100))
    source_filename: Mapped[str] = mapped_column(String(500))
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    mappings: Mapped[list["MicrosoftPracticeMapping"]] = relationship(back_populates="release", cascade="all, delete-orphan")


class MicrosoftPracticeMapping(Base):
    __tablename__ = "microsoft_practice_mappings"
    __table_args__ = (UniqueConstraint("release_id", "practice_identifier", name="uq_placemat_practice"), Index("ix_placemat_mapping_practice", "practice_identifier"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    release_id: Mapped[str] = mapped_column(ForeignKey("microsoft_placemat_releases.id"), index=True)
    practice_identifier: Mapped[str] = mapped_column(String(32), index=True)
    legacy_identifier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    requirement_statement: Mapped[str] = mapped_column(Text)
    primary_services: Mapped[list] = mapped_column(JSON)
    secondary_services: Mapped[list] = mapped_column(JSON)
    commercial_responsibility: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gcc_high_responsibility: Mapped[str | None] = mapped_column(String(64), nullable=True)
    nist_800_171_mapping: Mapped[str | None] = mapped_column(String(80), nullable=True)
    nist_800_53_mapping: Mapped[str | None] = mapped_column(Text, nullable=True)
    implementation_statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    release: Mapped[MicrosoftPlacematRelease] = relationship(back_populates="mappings")


class Practice(Base):
    __tablename__ = "practices"
    __table_args__ = (UniqueConstraint("identifier", name="uq_practice_identifier"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    domain_id: Mapped[str] = mapped_column(ForeignKey("domains.id"), index=True)
    identifier: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(Text)
    domain: Mapped[Domain] = relationship(back_populates="practices")
    objectives: Mapped[list["AssessmentObjective"]] = relationship(back_populates="practice", cascade="all, delete-orphan")


class AssessmentObjective(Base):
    __tablename__ = "assessment_objectives"
    __table_args__ = (UniqueConstraint("identifier", name="uq_objective_identifier"), Index("ix_objective_practice", "practice_id", "ordinal"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    practice_id: Mapped[str] = mapped_column(ForeignKey("practices.id"), index=True)
    identifier: Mapped[str] = mapped_column(String(40), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    statement: Mapped[str] = mapped_column(Text)
    practice: Mapped[Practice] = relationship(back_populates="objectives")
    rules: Mapped[list["TenantCheckRule"]] = relationship(back_populates="objective")


class TenantCheckRule(Base):
    __tablename__ = "tenant_check_rules"
    __table_args__ = (Index("ix_rule_objective_enabled", "objective_id", "enabled"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    objective_id: Mapped[str] = mapped_column(ForeignKey("assessment_objectives.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    graph_path: Mapped[str] = mapped_column(String(500))
    expected: Mapped[dict] = mapped_column(JSON)
    remediation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    objective: Mapped[AssessmentObjective] = relationship(back_populates="rules")


class AssessmentRun(Base):
    __tablename__ = "assessment_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    framework_release_id: Mapped[str | None] = mapped_column(ForeignKey("framework_releases.id"), nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    findings: Mapped[list["Finding"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    framework_release: Mapped[FrameworkRelease | None] = relationship()
    audit_review: Mapped["AuditEvidenceReview | None"] = relationship(back_populates="run", uselist=False, cascade="all, delete-orphan")


class AuditEvidenceReview(Base):
    """Assessor-entered context for directory-audit evidence; it does not set compliance automatically."""
    __tablename__ = "audit_evidence_reviews"
    __table_args__ = (UniqueConstraint("run_id", name="uq_audit_evidence_review_run"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("assessment_runs.id"), index=True)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    review_frequency: Mapped[str | None] = mapped_column(String(100), nullable=True)
    required_event_categories: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="NOT_STARTED", index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    run: Mapped[AssessmentRun] = relationship(back_populates="audit_review")


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (Index("ix_finding_run_objective", "run_id", "objective_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("assessment_runs.id"), index=True)
    objective_id: Mapped[str] = mapped_column(ForeignKey("assessment_objectives.id"), index=True)
    framework_objective_id: Mapped[str | None] = mapped_column(ForeignKey("framework_assessment_objectives.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    detail: Mapped[str] = mapped_column(Text)
    run: Mapped[AssessmentRun] = relationship(back_populates="findings")
    objective: Mapped[AssessmentObjective] = relationship()
    framework_objective: Mapped[FrameworkAssessmentObjective | None] = relationship()
    evidence: Mapped[list["EvidenceLog"]] = relationship(back_populates="finding", cascade="all, delete-orphan")
    remediation_plans: Mapped[list["RemediationPlan"]] = relationship(back_populates="finding", cascade="all, delete-orphan")
    poam_items: Mapped[list["PoamItem"]] = relationship(back_populates="finding")


class EvidenceLog(Base):
    __tablename__ = "evidence_logs"
    __table_args__ = (Index("ix_evidence_finding_captured", "finding_id", "captured_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"), index=True)
    source: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chain_hash: Mapped[str] = mapped_column(String(64), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finding: Mapped[Finding] = relationship(back_populates="evidence")


class RemediationPlan(Base):
    __tablename__ = "remediation_plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"), index=True)
    request: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(32), default="PROPOSED", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finding: Mapped[Finding] = relationship(back_populates="remediation_plans")
    approvals: Mapped[list["RemediationApproval"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class RemediationApproval(Base):
    __tablename__ = "remediation_approvals"
    __table_args__ = (UniqueConstraint("plan_id", "approver_id", name="uq_plan_approver"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    plan_id: Mapped[str] = mapped_column(ForeignKey("remediation_plans.id"), index=True)
    approver_id: Mapped[str] = mapped_column(String(200))
    mfa_confirmed: Mapped[bool] = mapped_column(Boolean)
    approved_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    plan: Mapped[RemediationPlan] = relationship(back_populates="approvals")


class PoamItem(Base):
    """A human-managed POA&M record; it never executes a tenant change."""
    __tablename__ = "poam_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    finding_id: Mapped[str | None] = mapped_column(ForeignKey("findings.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="OPEN", index=True)
    target_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    milestones: Mapped[list] = mapped_column(JSON, default=list)
    evidence_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    finding: Mapped[Finding | None] = relationship(back_populates="poam_items")
    change_records: Mapped[list["ChangeRecord"]] = relationship(back_populates="poam_item")
    objective_link: Mapped["ObjectivePoamLink | None"] = relationship(uselist=False)


class ObjectiveReviewRevision(Base):
    __tablename__ = "objective_review_revisions"
    __table_args__ = (UniqueConstraint("run_id", "objective_identifier", "revision", name="uq_objective_review_revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("assessment_runs.id"), index=True)
    objective_identifier: Mapped[str] = mapped_column(String(40), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    owner: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(32), default="NOT_STARTED")
    decision: Mapped[str] = mapped_column(String(32), default="NOT_ASSESSED")
    notes: Mapped[str] = mapped_column(Text, default="")
    resources: Mapped[list] = mapped_column(JSON, default=list)
    recorded_by: Mapped[str] = mapped_column(String(200))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditReviewRevision(Base):
    __tablename__ = "audit_review_revisions"
    __table_args__ = (UniqueConstraint("run_id", "revision", name="uq_audit_review_revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("assessment_runs.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    recorded_by: Mapped[str] = mapped_column(String(200))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditGapLink(Base):
    __tablename__ = "audit_gap_links"
    __table_args__ = (UniqueConstraint("run_id", "request_key", name="uq_audit_gap_request"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("assessment_runs.id"), index=True)
    poam_id: Mapped[str] = mapped_column(ForeignKey("poam_items.id"), unique=True)
    request_key: Mapped[str] = mapped_column(String(36))


class PoamRevision(Base):
    __tablename__ = "poam_revisions"
    __table_args__ = (UniqueConstraint("poam_id", "revision", name="uq_poam_revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    poam_id: Mapped[str] = mapped_column(ForeignKey("poam_items.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    recorded_by: Mapped[str] = mapped_column(String(200))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ObjectivePoamLink(Base):
    __tablename__ = "objective_poam_links"
    __table_args__ = (UniqueConstraint("run_id", "objective_identifier", "request_key", name="uq_objective_poam_request"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("assessment_runs.id"), index=True)
    objective_identifier: Mapped[str] = mapped_column(String(40), index=True)
    poam_id: Mapped[str] = mapped_column(ForeignKey("poam_items.id"), unique=True)
    request_key: Mapped[str] = mapped_column(String(36))


class PolicyException(Base):
    """Time-bounded exception decision kept separate from technical discovery evidence."""
    __tablename__ = "policy_exceptions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    objective_identifier: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    rationale: Mapped[str] = mapped_column(Text)
    compensating_controls: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ManagedAccount(Base):
    """Organization-managed account record; discovery and review do not modify Entra."""
    __tablename__ = "managed_accounts"
    __table_args__ = (UniqueConstraint("account_identifier", name="uq_managed_account_identifier"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    account_identifier: Mapped[str] = mapped_column(String(320), index=True)
    display_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    account_type: Mapped[str] = mapped_column(String(32), default="USER", index=True)
    privilege_level: Mapped[str] = mapped_column(String(32), default="STANDARD", index=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True)
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    mfa_status: Mapped[str] = mapped_column(String(32), default="UNKNOWN", index=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(120), default="MANUAL", index=True)
    source_id: Mapped[str | None] = mapped_column(String(240), nullable=True, index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    evidence_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InventoryAsset(Base):
    """Asset register for the CMMC system boundary; it does not establish authorization automatically."""
    __tablename__ = "inventory_assets"
    __table_args__ = (UniqueConstraint("asset_type", "asset_identifier", name="uq_inventory_asset_identifier"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    asset_type: Mapped[str] = mapped_column(String(32), index=True)
    asset_identifier: Mapped[str] = mapped_column(String(240), index=True)
    name: Mapped[str] = mapped_column(String(240), index=True)
    publisher_or_manufacturer: Mapped[str | None] = mapped_column(String(240), nullable=True)
    version_or_model: Mapped[str | None] = mapped_column(String(240), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    system_role: Mapped[str | None] = mapped_column(String(240), nullable=True)
    authorization_status: Mapped[str] = mapped_column(String(32), default="PENDING_REVIEW", index=True)
    cui_in_scope: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    lifecycle_status: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(120), default="MANUAL", index=True)
    source_id: Mapped[str | None] = mapped_column(String(240), nullable=True, index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    evidence_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    change_records: Mapped[list["ChangeRecord"]] = relationship(back_populates="asset")


class ChangeRecord(Base):
    """Approval-driven implementation record; it never executes a tenant change."""
    __tablename__ = "change_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(240), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_type: Mapped[str] = mapped_column(String(32), default="STANDARD", index=True)
    risk_level: Mapped[str] = mapped_column(String(32), default="MEDIUM", index=True)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True)
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    approver: Mapped[str | None] = mapped_column(String(200), nullable=True)
    planned_start_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    planned_end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rollback_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("inventory_assets.id"), nullable=True, index=True)
    poam_item_id: Mapped[str | None] = mapped_column(ForeignKey("poam_items.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    asset: Mapped[InventoryAsset | None] = relationship(back_populates="change_records")
    poam_item: Mapped[PoamItem | None] = relationship(back_populates="change_records")


class ScreenshotEvidence(Base):
    """User-approved screen capture retained as local supporting evidence."""
    __tablename__ = "screenshot_evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(240), index=True)
    objective_identifier: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    related_record_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    related_record_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    captured_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contains_cui: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(120), default="BROWSER_SCREEN_CAPTURE")
    content_type: Mapped[str] = mapped_column(String(100), default="image/png")
    byte_size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    image_data: Mapped[bytes] = mapped_column(LargeBinary)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

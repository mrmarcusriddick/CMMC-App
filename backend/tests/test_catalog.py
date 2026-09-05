from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from app.catalog import seed_catalog
from app.database import Base
from app.models import AssessmentObjective, ChangeRecord, InventoryAsset, ManagedAccount, PoamItem, PolicyException, Practice, ScreenshotEvidence


def test_seed_has_expected_cardinality():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_catalog(session)
        assert session.scalar(select(func.count()).select_from(Practice)) == 110
        assert session.scalar(select(func.count()).select_from(AssessmentObjective)) == 320


def test_governance_records_are_persisted_without_tenant_actions():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        poam = PoamItem(title="Review role MFA coverage", status="OPEN", milestones=["Assign owner"])
        exception = PolicyException(title="Temporary service exception", rationale="A documented business need exists.", status="DRAFT")
        session.add_all([poam, exception])
        session.commit()
        assert session.get(PoamItem, poam.id).milestones == ["Assign owner"]
        assert session.get(PolicyException, exception.id).rationale == "A documented business need exists."


def test_account_and_inventory_registers_are_local_records():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = ManagedAccount(account_identifier="admin@example.us", privilege_level="PRIVILEGED", mfa_status="UNKNOWN")
        asset = InventoryAsset(asset_type="SOFTWARE", asset_identifier="m365-apps", name="Microsoft 365 Apps", authorization_status="PENDING_REVIEW")
        session.add_all([account, asset])
        session.commit()
        assert session.get(ManagedAccount, account.id).privilege_level == "PRIVILEGED"
        assert session.get(InventoryAsset, asset.id).asset_type == "SOFTWARE"


def test_change_record_is_approval_driven_local_evidence():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        change = ChangeRecord(title="Update endpoint policy", change_type="NORMAL", risk_level="HIGH", status="DRAFT")
        session.add(change)
        session.commit()
        assert session.get(ChangeRecord, change.id).status == "DRAFT"


def test_screenshot_evidence_retains_hash_and_binary_content():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        screenshot = ScreenshotEvidence(title="Conditional Access review", byte_size=4, sha256="a" * 64, image_data=b"test")
        session.add(screenshot)
        session.commit()
        stored = session.get(ScreenshotEvidence, screenshot.id)
        assert stored.image_data == b"test"
        assert stored.sha256 == "a" * 64

from datetime import datetime, timedelta
from .config import get_settings


def build_remediation_request(rule: dict) -> dict:
    remediation = rule.get("remediation") or {}
    if remediation.get("template") != "require-mfa-for-directory-roles":
        raise ValueError("No approved remediation template is associated with this rule.")
    return {
        "method": "POST", "path": "/identity/conditionalAccess/policies",
        "body": {"displayName": "CMMC - Require MFA for directory roles", "state": "enabledForReportingButNotEnforced", "conditions": {"users": {"includeRoles": ["all_admin_roles"], "excludeUsers": [], "excludeGroups": []}, "applications": {"includeApplications": ["All"]}}, "grantControls": {"operator": "OR", "builtInControls": ["mfa"]}},
        "safety": "Created in report-only state; scope and exclusions require administrator validation before enforcing.",
    }


def execution_allowed(plan, approval_count: int) -> bool:
    settings = get_settings()
    return bool(settings.remediation_enabled and approval_count >= 2 and plan.expires_at > datetime.utcnow() and plan.state == "APPROVED")


def expiry() -> datetime:
    return datetime.utcnow() + timedelta(hours=4)

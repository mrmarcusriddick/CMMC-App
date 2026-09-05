import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
import httpx
from .graph import GraphClient


@dataclass(frozen=True)
class CheckResult:
    status: str
    evaluated_objective: str
    evidence: dict
    detail: str


def _canonical_hash(payload: dict, previous_hash: str | None = None) -> tuple[str, str]:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload_hash = hashlib.sha256(raw).hexdigest()
    chain_hash = hashlib.sha256(f"{previous_hash or ''}:{payload_hash}".encode()).hexdigest()
    return payload_hash, chain_hash


async def check_conditional_access_mfa(client: GraphClient) -> CheckResult:
    """Evaluate whether enabled Conditional Access policies protect directory roles with MFA."""
    objective = "AC.L2-3.1.1[a]"
    try:
        response = await client.get_json("/identity/conditionalAccess/policies", "Policy.Read.All")
    except PermissionError as exc:
        return CheckResult("MANUAL_REVIEW", objective, {"error": str(exc)}, "Read permission is missing; an assessor must review the configuration.")
    except (RuntimeError, httpx.HTTPError) as exc:
        return CheckResult("MANUAL_REVIEW", objective, {"error": str(exc)}, "Tenant discovery could not complete safely.")

    matching: list[dict] = []
    report_only: list[dict] = []
    exclusion_summaries: list[dict] = []
    covered_roles: set[str] = set()
    for policy in response.get("value", []):
        if not isinstance(policy, dict):
            continue
        conditions = policy.get("conditions") or {}
        users = conditions.get("users") if isinstance(conditions, dict) else {}
        roles = users.get("includeRoles", []) if isinstance(users, dict) else []
        exclusions = {key: len(users.get(key, []) or []) for key in ("excludeUsers", "excludeGroups", "excludeRoles") if isinstance(users, dict) and users.get(key)}
        controls = policy.get("grantControls") or {}
        if not isinstance(controls, dict):
            controls = {}
        has_mfa = "mfa" in (controls.get("builtInControls") or []) or bool(controls.get("authenticationStrength"))
        summary = {"id": policy.get("id"), "displayName": policy.get("displayName"), "state": policy.get("state"), "includeRoles": roles, "grantControls": controls}
        if policy.get("state") == "enabledForReportingButNotEnforced":
            report_only.append({"id": policy.get("id"), "displayName": policy.get("displayName")})
        if exclusions:
            exclusion_summaries.append({"id": policy.get("id"), "displayName": policy.get("displayName"), "excludedAssignmentCounts": exclusions})
        if policy.get("state") == "enabled" and roles and has_mfa:
            matching.append(summary)
            covered_roles.update(str(role) for role in roles)
    review_flags = []
    if report_only:
        review_flags.append({"type": "REPORT_ONLY_POLICIES", "count": len(report_only), "message": "Report-only policies do not enforce MFA and require assessor review."})
    if exclusion_summaries:
        review_flags.append({"type": "POLICY_EXCLUSIONS", "count": len(exclusion_summaries), "message": "Conditional Access exclusions require assessor review."})
    review_flags.append({"type": "ROLE_COVERAGE", "count": len(covered_roles), "message": "Compare covered role IDs with the in-scope privileged-role inventory; this connector does not read role assignments."})
    evidence = {"retrievedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"), "matchingPolicies": matching, "policyCount": len(response.get("value", [])), "reportOnlyPolicies": report_only, "exclusionSummaries": exclusion_summaries, "coveredRoleIds": sorted(covered_roles), "reviewFlags": review_flags}
    if matching:
        return CheckResult("COMPLIANT", objective, evidence, "At least one enabled policy applies MFA controls to administrative roles; validate exclusions and complete role coverage during assessment.")
    return CheckResult("NON_COMPLIANT", objective, evidence, "No enabled Conditional Access policy requiring MFA for administrative roles was discovered. Report-only policies do not satisfy this check.")


async def check_directory_audit_stream(client: GraphClient) -> CheckResult:
    """Confirm that a directory-audit evidence feed can be collected; do not infer retention or completeness."""
    objective = "AU.L2-3.3.1[a]"
    try:
        response = await client.get_json("/auditLogs/directoryAudits?$top=5", "AuditLog.Read.All")
    except PermissionError as exc:
        return CheckResult("MANUAL_REVIEW", objective, {"error": str(exc)}, "Directory audit-log access is not available; an assessor must collect and review audit evidence manually.")
    except (RuntimeError, httpx.HTTPError) as exc:
        return CheckResult("MANUAL_REVIEW", objective, {"error": str(exc)}, "Directory audit-log discovery could not complete safely.")

    sample = []
    for event in response.get("value", []):
        if isinstance(event, dict):
            sample.append({key: event.get(key) for key in ("activityDateTime", "activityDisplayName", "category", "result")})
    evidence = {"retrievedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"), "sampledEventCount": len(sample), "events": sample}
    return CheckResult("MANUAL_REVIEW", objective, evidence, "Directory audit records were retrieved. An assessor must validate event coverage, retention, review procedures, and alerting.")


async def check_privileged_role_inventory(client: GraphClient) -> CheckResult:
    """Inventory active directory roles and compare their role templates with enforced CA MFA policies."""
    objective = "IA.L2-3.5.3[a]"
    try:
        roles_response = await client.get_json("/directoryRoles?$select=id,displayName,roleTemplateId", "RoleManagement.Read.Directory")
        policies_response = await client.get_json("/identity/conditionalAccess/policies", "Policy.Read.All")
    except PermissionError as exc:
        return CheckResult("MANUAL_REVIEW", objective, {"error": str(exc)}, "Privileged-role inventory access is not available; an assessor must identify privileged accounts and roles manually.")
    except (RuntimeError, httpx.HTTPError) as exc:
        return CheckResult("MANUAL_REVIEW", objective, {"error": str(exc)}, "Privileged-role inventory discovery could not complete safely.")

    roles = [item for item in roles_response.get("value", []) if isinstance(item, dict) and item.get("roleTemplateId")]
    covered_templates: set[str] = set()
    excluded_templates: set[str] = set()
    for policy in policies_response.get("value", []):
        if not isinstance(policy, dict) or policy.get("state") != "enabled":
            continue
        controls = policy.get("grantControls") or {}
        if not isinstance(controls, dict) or not ("mfa" in (controls.get("builtInControls") or []) or bool(controls.get("authenticationStrength"))):
            continue
        users = (policy.get("conditions") or {}).get("users") or {}
        if not isinstance(users, dict):
            continue
        covered_templates.update(str(item) for item in (users.get("includeRoles") or []))
        excluded_templates.update(str(item) for item in (users.get("excludeRoles") or []))
    inventory = [{"displayName": role.get("displayName"), "roleTemplateId": role.get("roleTemplateId")} for role in roles]
    uncovered = [role for role in inventory if str(role["roleTemplateId"]) not in covered_templates]
    excluded = [role for role in inventory if str(role["roleTemplateId"]) in excluded_templates]
    review_flags = [{"type": "ROLE_INVENTORY", "count": len(inventory), "message": "Validate the in-scope privileged-account inventory and membership assignments."}]
    if uncovered:
        review_flags.append({"type": "UNCOVERED_PRIVILEGED_ROLES", "count": len(uncovered), "message": "Active directory roles are not included in an enabled MFA policy and require assessor review."})
    if excluded:
        review_flags.append({"type": "EXCLUDED_PRIVILEGED_ROLES", "count": len(excluded), "message": "Active directory roles are explicitly excluded from an enabled MFA policy and require assessor review."})
    evidence = {"retrievedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"), "activeDirectoryRoles": inventory, "coveredRoleTemplateCount": len(covered_templates), "uncoveredDirectoryRoles": uncovered, "excludedDirectoryRoles": excluded, "reviewFlags": review_flags}
    return CheckResult("MANUAL_REVIEW", objective, evidence, "Privileged directory roles were inventoried and compared with enabled Conditional Access MFA policies. An assessor must validate account membership and applicable access paths.")


AUTOMATED_CHECKS = (
    (check_conditional_access_mfa, "Microsoft Graph /identity/conditionalAccess/policies"),
    (check_directory_audit_stream, "Microsoft Graph /auditLogs/directoryAudits"),
    (check_privileged_role_inventory, "Microsoft Graph /directoryRoles and /identity/conditionalAccess/policies"),
)

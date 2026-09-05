import asyncio

from app.assessment import _canonical_hash, check_conditional_access_mfa, check_directory_audit_stream, check_privileged_role_inventory


def test_evidence_hash_is_deterministic_and_chained():
    first, chain = _canonical_hash({"b": 1, "a": 2})
    second, next_chain = _canonical_hash({"a": 2, "b": 1}, chain)
    assert first == second
    assert chain != next_chain


def test_null_grant_controls_is_safe_for_conditional_access_policy():
    class Client:
        async def get_json(self, _path, _permission):
            return {"value": [{"state": "enabled", "conditions": {"users": {"includeRoles": ["role-id"]}}, "grantControls": None}]}

    result = asyncio.run(check_conditional_access_mfa(Client()))
    assert result.status == "NON_COMPLIANT"
    assert result.evidence["policyCount"] == 1


def test_directory_audit_check_collects_a_minimal_event_sample():
    class Client:
        async def get_json(self, path, required_permission):
            assert path == "/auditLogs/directoryAudits?$top=5"
            assert required_permission == "AuditLog.Read.All"
            return {"value": [{"activityDateTime": "2026-01-01T00:00:00Z", "activityDisplayName": "Update policy", "category": "Policy", "result": "success", "initiatedBy": {"user": {"userPrincipalName": "not-retained@example.test"}}}]}

    result = asyncio.run(check_directory_audit_stream(Client()))
    assert result.status == "MANUAL_REVIEW"
    assert result.evidence["events"] == [{"activityDateTime": "2026-01-01T00:00:00Z", "activityDisplayName": "Update policy", "category": "Policy", "result": "success"}]


def test_report_only_conditional_access_policy_does_not_pass_mfa_check():
    class Client:
        async def get_json(self, _path, _permission):
            return {"value": [{"id": "policy-id", "displayName": "Report-only MFA", "state": "enabledForReportingButNotEnforced", "conditions": {"users": {"includeRoles": ["role-id"], "excludeGroups": ["group-id"]}}, "grantControls": {"builtInControls": ["mfa"]}}]}

    result = asyncio.run(check_conditional_access_mfa(Client()))
    assert result.status == "NON_COMPLIANT"
    assert {flag["type"] for flag in result.evidence["reviewFlags"]} == {"REPORT_ONLY_POLICIES", "POLICY_EXCLUSIONS", "ROLE_COVERAGE"}


def test_privileged_role_inventory_flags_uncovered_active_roles():
    class Client:
        async def get_json(self, path, _permission):
            if path.startswith("/directoryRoles"):
                return {"value": [{"displayName": "Global Administrator", "roleTemplateId": "covered"}, {"displayName": "Security Administrator", "roleTemplateId": "uncovered"}]}
            return {"value": [{"state": "enabled", "conditions": {"users": {"includeRoles": ["covered"]}}, "grantControls": {"builtInControls": ["mfa"]}}]}

    result = asyncio.run(check_privileged_role_inventory(Client()))
    assert result.status == "MANUAL_REVIEW"
    assert result.evidence["uncoveredDirectoryRoles"] == [{"displayName": "Security Administrator", "roleTemplateId": "uncovered"}]

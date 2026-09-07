# Application architecture

The application keeps framework content separate from discovery logic and tenant actions.

```text
CMMC catalog (domains → practices → objectives)
                 │
                 ├── TenantCheckRules ──→ Graph/Azure discovery adapters
                 │                              │
                 │                              └── Findings + hash-chained evidence
                 │                                           │
                 └─────────────────────────────── SSP / JSON evidence exports

Finding → remediation proposal → two MFA approvals → limited execution window → tenant write
```

`AssessmentObjective` is the stable compliance unit. `TenantCheckRule` maps it to a specific Graph endpoint and expected state, while `EvidenceLog` stores only the payload used to reach the decision. Changing Graph logic does not alter the control catalog; changing catalog wording does not alter a captured assessment.

## Runtime components

- **React/Vite frontend:** dashboards and evidence downloads only; it never obtains tenant credentials.
- **FastAPI:** validates requests, runs read-only discovery, persists assessment results, and creates exports.
- **PostgreSQL:** relational catalog and assessment data; JSON columns retain Graph evidence and controlled remediation payloads.
- **Microsoft Graph:** accessed app-only through managed identity where possible. The current check uses `GET /identity/conditionalAccess/policies`.
- **Remediation boundary:** proposals use a known request template, are report-only at creation, expire after four hours, and require two distinct approvers with a signed MFA confirmation. Writes remain disabled by default.

## Production hardening

The local dashboard now uses a single-operator password and a one-hour signed HttpOnly session cookie. All API records and evidence downloads require that session; Docker binds published ports to loopback. For shared deployment, replace the local gate with organizational SSO and role-based access, enable HTTPS and secure cookies, run database migrations rather than metadata creation, store evidence payloads in encrypted object storage where required, sign the evidence-chain root with a Key Vault key, and implement Graph change-control / rollback validation for each write template.

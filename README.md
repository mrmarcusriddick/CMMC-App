# CMMC Tenant Readiness

A secure, local-first CMMC Level 2 assessment application for Azure and Microsoft 365. It separates the CMMC catalog, tenant discovery, rule evaluation, immutable evidence, remediation proposals, and exports.

## What is included

- Normalized models for domains, practices, objectives, tenant check rules, assessment runs, findings, evidence, and approval-gated remediation plans.
- A seed catalog covering 14 CMMC Level 2 domains, 110 practices, and 320 objective records.
- Microsoft Graph conditional-access discovery that reports compliance, non-compliance, or manual review without modifying the tenant.
- SHA-256 evidence integrity hashes and a chain hash for each captured response.
- Two-person, expiring approval workflow before any remediation request can be executed.
- Markdown and JSON System Security Plan exports.
- A small React dashboard for running discovery and reviewing results.
- Importer for Microsoft Product Placemat `.xlsm` files that reads 110 Level 2 service and responsibility mappings without executing workbook macros.
- Parser that produces a SHA-256-bound CMMC v2.13 catalog package directly from the official Assessment Guide PDF, then validates its 110 practices and 320 objectives before import.
- New assessment runs link findings and SSP/evidence exports to the active source-validated framework release; historic development runs remain preserved as legacy evidence.

## Run locally

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Open `http://localhost:5173` for the dashboard and `http://localhost:8000/docs` for the API. The default local database is PostgreSQL in Docker. For development outside Docker, set `DATABASE_URL=sqlite:///./cmmc.db`.

## Tenant access

The app uses an Azure app registration with read-only Microsoft Graph application permissions and tenant-wide admin consent. The Conditional Access check requires `Policy.Read.All`; the audit-log readiness check requires `AuditLog.Read.All`; and privileged-role inventory requires `RoleManagement.Read.Directory`. Configure `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and use either workload identity / managed identity or `AZURE_CLIENT_SECRET`. Set `AZURE_CLOUD=usgovernment` for GCC High, `usgovernmentdod` for DoD, or leave `public` for commercial tenants. Do not use a client secret in production; use a managed identity or Key Vault reference.

Remediation is disabled unless `REMEDIATION_ENABLED=true`. Even then, every action requires two distinct approvers, an MFA-confirmed approval webhook, and an unexpired execution window.

## Important

This tool organizes evidence and automates technical checks; it does not certify CMMC compliance. The seed objective records preserve the required catalog cardinality and should be reviewed against the assessor guide/version governing the engagement before an assessment.

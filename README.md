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
./scripts/Initialize-LocalAccess.ps1
docker compose up --build
```

Open `http://localhost:5173` for the dashboard and `http://localhost:8000/docs` for the API. The default local database is PostgreSQL in Docker. For development outside Docker, set `DATABASE_URL=sqlite:///./cmmc.db`.

Sign in with `APP_USERNAME` and `APP_PASSWORD` from your local `.env`. The initialization script generates a random password and preserves existing credentials; it never prints the password. The API refuses sign-in when the password is missing or shorter than 24 characters. Keep `.env` untracked.

Both published ports bind only to `127.0.0.1`. All `/api/` records, image downloads, and exports require a one-hour HttpOnly, SameSite=Strict session cookie. Sign out clears that browser's cookie; rotating `APP_PASSWORD` and restarting the API invalidates all existing sessions. This is a single-operator local access gate, not per-user authorization or organizational SSO. Shared hosting requires HTTPS (`SESSION_COOKIE_SECURE=true`), organizational authentication, and role-based authorization. API documentation and the generic health response contain no assessment data and remain public.

## Screenshot evidence

Use **Capture evidence**, enter a title, then select a screen, window, or tab in the browser picker. Sharing stops immediately after the still frame is copied, before PNG encoding and upload. There is no second preview/approval step. Captures retain their original uploaded bytes and SHA-256 hash; the server validates image contents, limits size to 20 MB and dimensions to 16 million pixels, and records the signed-in operator. The CUI checkbox is metadata and does not add encryption or a separate access policy.

Frontend capture lifecycle tests run with `cd frontend; npm test`. Backend tests in `backend/tests` require pytest and the backend requirements; run `python -m pytest tests` from `backend` with an isolated SQLite `DATABASE_URL`. The screenshot API tests use their own in-memory database, not the live evidence database.

## Audit reviews

Open **Audit reviews** to select an assessment, assign its review owner, record retention and required event categories, and schedule the next review. Filter the queue by owner/tenant/run, conclusion, or overdue next-review date (UTC). The schedule is entered explicitly and does not send notifications or automatically roll dates forward.

Attach discovery evidence from that assessment or relevant local screenshots. A Supported conclusion requires evidence, retention, frequency, event categories, an owner, and rationale; Gap and Not applicable require an owner and rationale. Each save records the operator, time, evidence references/hashes, and full review state. Earlier notes are retained as the original baseline on first edit. Concurrent stale saves are rejected; **Reload saved review** retrieves the latest state.

A saved Gap conclusion can create a POA&M item linked to an AU objective in the assessment's catalog. It inherits the review owner and rationale; manage its milestones, evidence, and closure in POA&M. Audit conclusions do not automatically change technical findings or objective decisions. The assessment-run form now opens this workspace rather than maintaining a separate unversioned editor.

## POA&M management

Open **POA&M** to filter gaps by status, owner/title/objective text, or overdue target date (UTC). Select a record to edit its owner, due date, milestones, and evidence reference. Objective and assessment-summary gap links open the same detail page. New standalone records begin open, in progress, or blocked; objective-linked gaps can be created from a saved Not met review.

Completing or closing a gap requires an owner, completed milestones, closure notes, and an evidence reference or attached screenshot. Saves preserve revision history (including the original baseline on first edit) and reject stale updates. **Reload saved gap** retrieves another session's changes. Closing a linked gap adds its objective to the **Re-review after closure** summary queue until a later completed objective review is saved. Closure never changes technical findings or reviewer decisions automatically. History retains screenshot IDs, titles, and SHA-256 hashes. These are local workflow records, not tenant remediation actions.

## Objective reviews

Open **Objective reviews** (or select it in the workspace menu on smaller screens), choose an assessment run, and select an objective. The list uses that run's catalog release; older runs without a release are explicitly labeled as unverified seed content. Filter by domain or review status, or search objective wording and owner.

The detail page shows technical findings separately from the human review. Assign an owner, enter review notes and a decision, and attach discovery evidence, screenshots, or local supporting records. A completed review requires an owner, a decision, and rationale. Every save appends a revision with the signed-in operator, timestamp, resource labels, and available evidence hashes. Stale saves return a conflict instead of overwriting a newer review. Reviews do not change automated findings, assessment summaries, or existing SSP exports.

A saved **Not met** decision enables creation of a linked POA&M item, including when no automated finding exists. Retries of the same creation request do not duplicate the item. Links to an objective preserve the assessment run and identifier. Screenshots and other local records are workspace-wide; reviewers must confirm their applicability. The revision history is application-level history in the local database, not a tamper-proof audit service.

## Assessment summary and review reports

Open **Assessment summary** and select a run to see domain progress, finalized human decisions, and queues for missing owners, missing attachments, or pending decisions. Progress counts the latest saved review for every objective in that run's catalog. Only complete reviews contribute to finalized decision counts; provisional decisions remain separate. Not-applicable objectives remain in the workflow-progress denominator. These totals measure review work, not certification or a compliance score.

Linked POA&M items include both direct objective links and links through findings from the selected run. An item is overdue when its target UTC date is before today and its status is not complete, closed, or cancelled. Unlinked workspace gaps are excluded. Queue filters do not change the exported report.

Download review JSON or Markdown for a current snapshot containing all objective statements, latest reviewer decisions, rationale, revision attribution, evidence references and hashes, technical findings, and linked gaps. These new reports supplement existing SSP and raw discovery exports. Refresh the summary to include changes made in another session.

## Tenant access

The app uses an Azure app registration with read-only Microsoft Graph application permissions and tenant-wide admin consent. The Conditional Access check requires `Policy.Read.All`; the audit-log readiness check requires `AuditLog.Read.All`; and privileged-role inventory requires `RoleManagement.Read.Directory`. Configure `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and use either workload identity / managed identity or `AZURE_CLIENT_SECRET`. Set `AZURE_CLOUD=usgovernment` for GCC High, `usgovernmentdod` for DoD, or leave `public` for commercial tenants. Do not use a client secret in production; use a managed identity or Key Vault reference.

Remediation is disabled unless `REMEDIATION_ENABLED=true`. Even then, every action requires two distinct approvers, an MFA-confirmed approval webhook, and an unexpired execution window.

## Important

This tool organizes evidence and automates technical checks; it does not certify CMMC compliance. The seed objective records preserve the required catalog cardinality and should be reviewed against the assessor guide/version governing the engagement before an assessment.

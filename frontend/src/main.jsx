import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './operations.css';
import { captureStill } from './capture.mjs';
import ObjectiveWorkspace from './ObjectiveWorkspace';
import AssessmentSummary from './AssessmentSummary';
import PoamWorkspace from './PoamWorkspace';
import AuditWorkspace from './AuditWorkspace';
import EndpointWorkspace from './EndpointWorkspace';

const navGroups = [
  { label: 'WORKSPACE', items: [['overview', '◈', 'Overview'], ['assessments', '▤', 'Assessment runs'], ['objectives', '◎', 'Objective reviews'], ['summary', '▥', 'Assessment summary'], ['evidence', '▧', 'Evidence vault'], ['screenshots', '▣', 'Capture evidence']] },
  { label: 'DATABASES', items: [['accounts', '♧', 'Account management'], ['changes', '⌁', 'Change management'], ['software', '▣', 'Software inventory'], ['hardware', '▤', 'Windows endpoint readiness'], ['poam', '◎', 'POA&M']] },
  { label: 'OPERATIONS', items: [['audit', '✓', 'Audit reviews']] },
];
const accountDefaults = { accountIdentifier: '', displayName: '', accountType: 'USER', privilegeLevel: 'STANDARD', status: 'ACTIVE', owner: '', mfaStatus: 'UNKNOWN', lastReviewedAt: '', evidenceReference: '' };
const assetDefaults = { assetIdentifier: '', name: '', publisherOrManufacturer: '', versionOrModel: '', owner: '', systemRole: '', authorizationStatus: 'PENDING_REVIEW', cuiInScope: false, lifecycleStatus: 'ACTIVE', lastReviewedAt: '', evidenceReference: '', notes: '' };
const changeDefaults = { title: '', description: '', changeType: 'STANDARD', riskLevel: 'MEDIUM', status: 'DRAFT', owner: '', approver: '', plannedStartAt: '', plannedEndAt: '', rollbackPlan: '', evidenceReference: '', assetId: '', poamItemId: '' };
const screenshotDefaults = { title: '', objectiveIdentifier: '', relatedRecordType: '', relatedRecordId: '', capturedBy: '', containsCui: false, notes: '' };
const fmt = value => value ? new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(value)) : '—';
const statusText = value => (value || 'NOT_STARTED').replaceAll('_', ' ');

function Status({ value }) { return <span className={`status status-${(value || 'not_started').toLowerCase()}`}>{statusText(value)}</span>; }
function Empty({ title, body }) { return <div className="empty"><div>◌</div><h3>{title}</h3><p>{body}</p></div>; }

function App() {
  const [session, setSession] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [loginForm, setLoginForm] = useState({ username: 'localadmin', password: '' });
  const [signingIn, setSigningIn] = useState(false);
  const [objectiveDirty, setObjectiveDirty] = useState(false);
  const [page, setPage] = useState(() => window.location.hash.startsWith('#objectives') ? 'objectives' : window.location.hash.startsWith('#summary') ? 'summary' : window.location.hash.startsWith('#poam') ? 'poam' : window.location.hash.startsWith('#audit') ? 'audit' : window.location.hash.startsWith('#hardware') ? 'hardware' : 'overview');
  const [summary, setSummary] = useState(null);
  const [overview, setOverview] = useState(null);
  const [assessments, setAssessments] = useState([]);
  const [evidence, setEvidence] = useState([]);
  const [poam, setPoam] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [assets, setAssets] = useState([]);
  const [changes, setChanges] = useState([]);
  const [screenshots, setScreenshots] = useState([]);
  const [accountForm, setAccountForm] = useState(accountDefaults);
  const [assetForm, setAssetForm] = useState(assetDefaults);
  const [changeForm, setChangeForm] = useState(changeDefaults);
  const [screenshotForm, setScreenshotForm] = useState(screenshotDefaults);
  const [capturing, setCapturing] = useState(false);
  const [query, setQuery] = useState('');
  const [tenantId, setTenantId] = useState('');
  const [runResult, setRunResult] = useState(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  async function loadData() {
    const access = await fetch('/api/session');
    if (access.status === 401) { setSession(null); return; }
    if (!access.ok) throw new Error('Local sign-in service is unavailable.');
    const values = await Promise.all(['/api/catalog/summary', '/api/dashboard/overview', '/api/assessments', '/api/evidence', '/api/poam', '/api/accounts', '/api/inventory', '/api/changes', '/api/screenshots'].map(url => fetch(url).then(response => response.ok ? response.json() : null).catch(() => null)));
    const [catalog, dash, runList, evidenceList, poamList, accountList, assetList, changeList, screenshotList] = values;
    if (!catalog || !dash) setError('Some local dashboard data could not be loaded.');
    setSummary(catalog); setOverview(dash); setAssessments(runList?.items || []); setEvidence(evidenceList?.items || []); setPoam(poamList?.items || []); setAccounts(accountList?.items || []); setAssets(assetList?.items || []); setChanges(changeList?.items || []); setScreenshots(screenshotList?.items || []);
  }
  useEffect(() => {
    fetch('/api/session').then(async response => {
      if (response.ok) { setSession(await response.json()); await loadData(); }
      else if (response.status !== 401) setError('Local sign-in service is unavailable.');
    }).catch(() => setError('The local app could not be reached.')).finally(() => setCheckingSession(false));
  }, []);

  async function signIn(event) {
    event.preventDefault(); setError(''); setSigningIn(true);
    try {
      const response = await fetch('/api/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(loginForm) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Sign-in failed.');
      setSession(data); setLoginForm({ username: loginForm.username, password: '' }); await loadData();
    } catch (err) { setError(err.message); }
    finally { setSigningIn(false); }
  }

  async function signOut() {
    if (objectiveDirty && !window.confirm('Leave this page and sign out? Unsaved changes will be lost.')) return;
    try {
      const response = await fetch('/api/session', { method: 'DELETE' });
      if (!response.ok && response.status !== 401) throw new Error('Sign-out failed. Please try again.');
      window.location.reload();
    } catch (err) { setError(err.message); }
  }

  function goToPage(next) {
    if (next === page) return;
    if (objectiveDirty && !window.confirm('Leave this page? Unsaved changes will be lost.')) return;
    setPage(next); setQuery('');
    if (next === 'summary' || next === 'objectives' || next === 'audit') { const run = new URLSearchParams(window.location.hash.split('?')[1] || '').get('run'); window.history.replaceState(null, '', '#' + next + (run ? '?' + new URLSearchParams({ run }) : '')); } else window.history.replaceState(null, '', window.location.pathname + window.location.search);
  }

  function openPoam(id) {
    if (objectiveDirty && !window.confirm('Discard unsaved changes?')) return;
    window.history.replaceState(null, '', '#poam?' + new URLSearchParams({ id })); setObjectiveDirty(false); setPage('poam');
  }

  async function runAssessment(event) {
    event.preventDefault(); setError(''); setMessage(''); setRunResult(null);
    const response = await fetch('/api/assessments', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tenant_id: tenantId }) });
    const data = await response.json();
    if (!response.ok) return setError(data.detail || 'Assessment could not start.');
    setRunResult(data); setMessage('Read-only discovery completed and evidence was recorded locally.'); await loadData();
  }




  async function createAccount(event) {
    event.preventDefault(); setError(''); setMessage('');
    const payload = { account_identifier: accountForm.accountIdentifier, display_name: accountForm.displayName || null, account_type: accountForm.accountType, privilege_level: accountForm.privilegeLevel, status: accountForm.status, owner: accountForm.owner || null, mfa_status: accountForm.mfaStatus, last_reviewed_at: accountForm.lastReviewedAt ? new Date(`${accountForm.lastReviewedAt}T12:00:00`).toISOString() : null, evidence_reference: accountForm.evidenceReference || null };
    const response = await fetch('/api/accounts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await response.json();
    if (!response.ok) return setError(data.detail || 'Account record could not be saved.');
    setAccountForm(accountDefaults); setMessage('Account record saved locally. It does not change the Entra account.'); await loadData();
  }

  async function createAsset(event, assetType) {
    event.preventDefault(); setError(''); setMessage('');
    const payload = { asset_type: assetType, asset_identifier: assetForm.assetIdentifier, name: assetForm.name, publisher_or_manufacturer: assetForm.publisherOrManufacturer || null, version_or_model: assetForm.versionOrModel || null, owner: assetForm.owner || null, system_role: assetForm.systemRole || null, authorization_status: assetForm.authorizationStatus, cui_in_scope: assetForm.cuiInScope, lifecycle_status: assetForm.lifecycleStatus, last_reviewed_at: assetForm.lastReviewedAt ? new Date(`${assetForm.lastReviewedAt}T12:00:00`).toISOString() : null, evidence_reference: assetForm.evidenceReference || null, notes: assetForm.notes || null };
    const response = await fetch('/api/inventory', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await response.json();
    if (!response.ok) return setError(data.detail || 'Inventory record could not be saved.');
    setAssetForm(assetDefaults); setMessage(`${assetType === 'SOFTWARE' ? 'Software' : 'Hardware'} inventory record saved locally.`); await loadData();
  }

  async function syncFromTenant(kind) {
    setError(''); setMessage('');
    const response = await fetch(`/api/sync/${kind}`, { method: 'POST' });
    const data = await response.json();
    if (!response.ok) return setError(data.detail || 'Tenant sync could not complete.');
    const total = kind === 'accounts' ? data.total : (data.counts.hardware.created + data.counts.hardware.updated + data.counts.software.created + data.counts.software.updated);
    setMessage(`${kind === 'accounts' ? 'Account' : 'Inventory'} sync completed: ${total} records added or refreshed. ${data.warnings?.length ? data.warnings.join(' ') : ''}`); await loadData();
  }

  async function createChange(event) {
    event.preventDefault(); setError(''); setMessage('');
    const toIso = value => value ? new Date(`${value}T12:00:00`).toISOString() : null;
    const payload = { title: changeForm.title, description: changeForm.description || null, change_type: changeForm.changeType, risk_level: changeForm.riskLevel, status: changeForm.status, owner: changeForm.owner || null, approver: changeForm.approver || null, planned_start_at: toIso(changeForm.plannedStartAt), planned_end_at: toIso(changeForm.plannedEndAt), rollback_plan: changeForm.rollbackPlan || null, evidence_reference: changeForm.evidenceReference || null, asset_id: changeForm.assetId || null, poam_item_id: changeForm.poamItemId || null };
    const response = await fetch('/api/changes', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await response.json();
    if (!response.ok) return setError(data.detail || 'Change record could not be saved.');
    setChangeForm(changeDefaults); setMessage('Change record saved locally. It does not execute a tenant change.'); await loadData();
  }

  async function captureScreenshot() {
    const title = screenshotForm.title.trim();
    if (title.length < 3) return setError('Enter a screenshot title before starting capture.');
    if (!navigator.mediaDevices?.getDisplayMedia) return setError('Screen capture is not supported by this browser. Use a current desktop browser and select a screen, window, or tab.');
    setCapturing(true); setError(''); setMessage('');
    try {
      const image = await captureStill();
      const params = new URLSearchParams({ title, contains_cui: String(screenshotForm.containsCui) });
      if (screenshotForm.objectiveIdentifier) params.set('objective_identifier', screenshotForm.objectiveIdentifier);
      if (screenshotForm.relatedRecordType) params.set('related_record_type', screenshotForm.relatedRecordType);
      if (screenshotForm.relatedRecordId) params.set('related_record_id', screenshotForm.relatedRecordId);
      if (screenshotForm.capturedBy) params.set('captured_by', screenshotForm.capturedBy);
      if (screenshotForm.notes) params.set('notes', screenshotForm.notes);
      const response = await fetch(`/api/screenshots?${params.toString()}`, { method: 'POST', headers: { 'Content-Type': 'image/png' }, body: image });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Screenshot evidence could not be saved.');
      setScreenshotForm(screenshotDefaults); setMessage('Screenshot captured with your approval, hashed, and stored as local evidence.'); await loadData();
    } catch (captureError) {
      const messageText = captureError?.name === 'NotAllowedError' ? 'Screen capture was cancelled or not permitted. No screenshot was saved.' : (captureError?.message || 'Screenshot capture could not complete.');
      setError(messageText);
    } finally {
      setCapturing(false);
    }
  }

  const filteredAssessments = useMemo(() => assessments.filter(item => `${item.tenantId} ${item.overallStatus} ${item.frameworkVersion}`.toLowerCase().includes(query.toLowerCase())), [assessments, query]);
  const filteredEvidence = useMemo(() => evidence.filter(item => `${item.objective} ${item.source} ${item.status}`.toLowerCase().includes(query.toLowerCase())), [evidence, query]);
  const filteredAccounts = useMemo(() => accounts.filter(item => `${item.accountIdentifier} ${item.displayName || ''} ${item.owner || ''} ${item.privilegeLevel} ${item.mfaStatus}`.toLowerCase().includes(query.toLowerCase())), [accounts, query]);
  const filteredAssets = type => assets.filter(item => item.assetType === type && `${item.assetIdentifier} ${item.name} ${item.publisherOrManufacturer || ''} ${item.owner || ''} ${item.authorizationStatus}`.toLowerCase().includes(query.toLowerCase()));
  const filteredChanges = useMemo(() => changes.filter(item => `${item.title} ${item.owner || ''} ${item.changeType} ${item.riskLevel} ${item.status}`.toLowerCase().includes(query.toLowerCase())), [changes, query]);
  const pageTitle = { overview: 'Overview', summary: 'Assessment summary', objectives: 'Objective reviews', assessments: 'Assessment runs', evidence: 'Evidence vault', screenshots: 'Capture evidence', accounts: 'Account management', changes: 'Change management', software: 'Software inventory', hardware: 'Windows endpoint readiness', poam: 'POA&M', audit: 'Audit reviews' }[page];
  const currentAssetType = page === 'software' ? 'SOFTWARE' : 'HARDWARE';
  const counts = overview?.findings || { compliant: 0, manualReview: 0, nonCompliant: 0 };
  const runningFindings = runResult?.findings || [];

  if (checkingSession) return <main className="login-page"><p>Opening local workspace…</p></main>;
  if (!session) return <main className="login-page"><form className="panel login-panel" onSubmit={signIn}><h1>CMMC Compass</h1><p>Sign in to access your local records and evidence.</p>{error && <div className="alert error-alert">{error}</div>}<label>Username<input autoComplete="username" value={loginForm.username} onChange={event => setLoginForm({ ...loginForm, username: event.target.value })} required/></label><label>Password<input type="password" autoComplete="current-password" value={loginForm.password} onChange={event => setLoginForm({ ...loginForm, password: event.target.value })} required/></label><button type="submit" disabled={signingIn}>{signingIn ? 'Signing in…' : 'Sign in'}</button></form></main>;

  return <div className="shell">
    <aside className="sidebar"><div className="brand"><span className="brand-mark">◇</span><div><b>CMMC Compass</b><small>Tenant readiness</small></div></div><nav>{navGroups.map(group => <div className="nav-group" key={group.label}><p>{group.label}</p>{group.items.map(([id, icon, label]) => <button key={id} className={page === id ? 'nav-item active' : 'nav-item'} onClick={() => goToPage(id)}><span>{icon}</span>{label}{id === 'assessments' && <em>{assessments.length}</em>}{id === 'evidence' && <em>{evidence.length}</em>}{id === 'screenshots' && <em>{screenshots.length}</em>}{id === 'accounts' && <em>{accounts.length}</em>}{id === 'changes' && <em>{changes.length}</em>}{id === 'software' && <em>{assets.filter(item => item.assetType === 'SOFTWARE').length}</em>}{id === 'hardware' && <em>{assets.filter(item => item.assetType === 'HARDWARE').length}</em>}{id === 'poam' && <em>{poam.length}</em>}</button>)}</div>)}</nav><div className="sidebar-footer"><span className="dot"/> GCC High connected<br/><small>Read-only discovery</small></div></aside>
    <main className="workspace"><header className="topbar"><div><span className="eyebrow">CMMC LEVEL 2 · GCC HIGH</span><h1>{pageTitle}</h1></div><div className="toolbar"><label className="search">⌕<input value={query} onChange={event => setQuery(event.target.value)} placeholder={page === 'evidence' ? 'Search evidence' : 'Search records'}/></label><button className="export" onClick={() => goToPage('evidence')}>⇩ Evidence exports</button><button className="export" onClick={signOut}>Sign out</button></div></header>
      <select className="mobile-navigation" aria-label="Workspace page" value={page} onChange={event => goToPage(event.target.value)}>{navGroups.flatMap(group => group.items).map(([id, , label]) => <option key={id} value={id}>{label}</option>)}</select>
      {page === 'summary' && <AssessmentSummary onOpenPoam={openPoam} runs={assessments} onAuthExpired={() => setSession(null)} onOpenObjective={(run, objective) => { window.history.replaceState(null, '', '#objectives?' + new URLSearchParams({ run, objective })); setPage('objectives'); }}/>}
      {page === 'objectives' && <ObjectiveWorkspace onOpenPoam={openPoam} runs={assessments} onAuthExpired={() => setSession(null)} onDirty={setObjectiveDirty} onRecordsChanged={loadData}/>}
      {!['objectives', 'summary'].includes(page) && summary?.framework?.status === 'SOURCE_VALIDATED' && <div className="baseline"><b>Source-validated baseline</b><span>CMMC Level 2 v{summary.framework.version} · 110 practices · 320 objectives</span></div>}
      {error && <div className="alert error-alert">{error}</div>}{message && <div className="alert success-alert">{message}</div>}
      {page === 'overview' && <>
        <section className="metric-grid"><article><span>Assessment runs</span><b>{overview?.assessmentCount ?? '—'}</b><small>Local evidence history</small></article><article><span>Compliant findings</span><b>{counts.compliant}</b><small>Technical signals, not certification</small></article><article><span>Manual review</span><b>{counts.manualReview}</b><small>Assessor action required</small></article><article><span>Open gaps</span><b>{counts.nonCompliant}</b><small>Requires remediation decision</small></article></section>
        <section className="split"><div className="panel"><div className="panel-head"><div><h2>Run tenant discovery</h2><p>Creates immutable local evidence. No Microsoft settings are changed.</p></div><Status value="READ_ONLY"/></div><form className="run-form" onSubmit={runAssessment}><input required value={tenantId} onChange={event => setTenantId(event.target.value)} placeholder="Microsoft Entra tenant ID"/><button>Run assessment</button></form>{runningFindings.length > 0 && <div className="run-findings">{runningFindings.map(finding => <div key={finding.id}><Status value={finding.status}/><b>{finding.objective}</b><p>{finding.detail}</p>{finding.reviewFlags?.map(flag => <small className="flag" key={flag.type}>• {flag.message}</small>)}</div>)}<div className="download-row"><a href={`/api/assessments/${runResult.runId}/ssp.md`}>Download SSP</a><a href={`/api/assessments/${runResult.runId}/evidence.json`}>Download evidence JSON</a></div></div>}</div>
        <div className="panel"><div className="panel-head"><div><h2>Review queue</h2><p>Recent assessment activity</p></div><button className="text-button" onClick={() => setPage('assessments')}>View all →</button></div>{overview?.recentRuns?.length ? <div className="compact-list">{overview.recentRuns.map(run => <button key={run.id} onClick={() => setPage('assessments')}><div><b>{run.tenantId.slice(0, 8)}…</b><small>{fmt(run.startedAt)}</small></div><Status value={run.overallStatus}/></button>)}</div> : <Empty title="No assessments yet" body="Run read-only discovery to begin the evidence trail."/>}</div></section>
        {runResult && <section className="panel poam-panel"><h2>Audit evidence review</h2><button onClick={() => { window.history.replaceState(null, '', '#audit?' + new URLSearchParams({ run: runResult.runId })); setPage('audit'); }}>Open audit review</button></section>}
      </>}
      {page === 'assessments' && <section className="panel table-panel"><div className="panel-head"><div><h2>Assessment records</h2><p>{filteredAssessments.length} records · New records are bound to CMMC v2.13.</p></div></div>{filteredAssessments.length ? <table><thead><tr><th>Tenant</th><th>Framework</th><th>Status</th><th>Findings</th><th>Manual review</th><th>Started</th></tr></thead><tbody>{filteredAssessments.map(run => <tr key={run.id}><td><b>{run.tenantId}</b><small>{run.id.slice(0, 8)}</small></td><td>v{run.frameworkVersion || 'legacy'}</td><td><Status value={run.overallStatus}/></td><td>{run.findingCount}</td><td>{run.manualReviewCount}</td><td>{fmt(run.startedAt)}</td></tr>)}</tbody></table> : <Empty title="No matching assessments" body="Try a different search or run a new assessment."/>}</section>}
      {page === 'evidence' && <section className="panel table-panel"><div className="panel-head"><div><h2>Evidence vault</h2><p>Hash-chained records captured from read-only discovery.</p></div></div>{filteredEvidence.length ? <table><thead><tr><th>Objective</th><th>Source</th><th>Status</th><th>Captured</th><th>Export</th></tr></thead><tbody>{filteredEvidence.map(item => <tr key={item.id}><td><b>{item.objective}</b><small>{item.payloadHash.slice(0, 12)}…</small></td><td>{item.source.replace('Microsoft Graph ', '')}</td><td><Status value={item.status}/></td><td>{fmt(item.capturedAt)}</td><td><a href={`/api/assessments/${item.runId}/evidence.json`}>JSON ↗</a></td></tr>)}</tbody></table> : <Empty title="No matching evidence" body="Run an assessment to capture local evidence."/>}</section>}
      {page === 'poam' && <PoamWorkspace screenshots={screenshots} onAuthExpired={() => setSession(null)} onDirty={setObjectiveDirty} onRecordsChanged={loadData} onOpenObjective={(run, objective) => { window.history.replaceState(null, '', '#objectives?' + new URLSearchParams({ run, objective })); setObjectiveDirty(false); setPage('objectives'); }}/>}
      {page === 'hardware' && <EndpointWorkspace runs={assessments} screenshots={screenshots} onDirty={setObjectiveDirty} onAuthExpired={() => setSession(null)} onRecordsChanged={loadData} onOpenPoam={openPoam}/>}
      {page === 'audit' && <AuditWorkspace screenshots={screenshots} onDirty={setObjectiveDirty} onAuthExpired={() => setSession(null)} onRecordsChanged={loadData} onOpenPoam={openPoam}/>}
      {page === 'accounts' && <><section className="panel record-form-panel"><div className="panel-head"><div><h2>Add account review record</h2><p>Local account governance record. It does not create, change, or disable the Entra account.</p></div><Status value="PENDING_REVIEW"/></div><form className="record-grid" onSubmit={createAccount}><label>Account identifier<input required minLength="3" value={accountForm.accountIdentifier} onChange={event => setAccountForm({...accountForm, accountIdentifier: event.target.value})} placeholder="name@organization.us"/></label><label>Display name<input value={accountForm.displayName} onChange={event => setAccountForm({...accountForm, displayName: event.target.value})} placeholder="Person, service, or shared account"/></label><label>Account type<select value={accountForm.accountType} onChange={event => setAccountForm({...accountForm, accountType: event.target.value})}>{['USER','SERVICE','SHARED','BREAK_GLASS','EXTERNAL'].map(value => <option key={value}>{value}</option>)}</select></label><label>Privilege level<select value={accountForm.privilegeLevel} onChange={event => setAccountForm({...accountForm, privilegeLevel: event.target.value})}>{['STANDARD','PRIVILEGED','GLOBAL_ADMIN','EMERGENCY'].map(value => <option key={value}>{value}</option>)}</select></label><label>Lifecycle status<select value={accountForm.status} onChange={event => setAccountForm({...accountForm, status: event.target.value})}>{['ACTIVE','DISABLED','PENDING_REVIEW','TERMINATED'].map(value => <option key={value}>{value}</option>)}</select></label><label>MFA status<select value={accountForm.mfaStatus} onChange={event => setAccountForm({...accountForm, mfaStatus: event.target.value})}>{['ENFORCED','EXCLUDED','NOT_ENROLLED','UNKNOWN','NOT_APPLICABLE'].map(value => <option key={value}>{value}</option>)}</select></label><label>Owner<input value={accountForm.owner} onChange={event => setAccountForm({...accountForm, owner: event.target.value})} placeholder="Responsible manager or team"/></label><label>Last reviewed<input type="date" value={accountForm.lastReviewedAt} onChange={event => setAccountForm({...accountForm, lastReviewedAt: event.target.value})}/></label><label className="wide">Evidence reference<textarea value={accountForm.evidenceReference} onChange={event => setAccountForm({...accountForm, evidenceReference: event.target.value})} placeholder="Access review, ticket, or supporting evidence reference"/></label><button>Save account record</button></form></section><section className="panel table-panel"><div className="panel-head"><div><h2>Account management register</h2><p>{filteredAccounts.length} organization-managed records.</p></div></div>{filteredAccounts.length ? <table><thead><tr><th>Account</th><th>Type</th><th>Privilege</th><th>MFA</th><th>Status</th><th>Reviewed</th></tr></thead><tbody>{filteredAccounts.map(item => <tr key={item.id}><td><b>{item.accountIdentifier}</b><small>{item.displayName || 'No display name'}</small></td><td>{statusText(item.accountType)}</td><td><Status value={item.privilegeLevel}/></td><td><Status value={item.mfaStatus}/></td><td><Status value={item.status}/></td><td>{fmt(item.lastReviewedAt)}</td></tr>)}</tbody></table> : <Empty title="No account records" body="Record privileged, service, shared, emergency, and user accounts as they are reviewed."/>}</section></>}
      {page === 'software' && <><section className="panel record-form-panel"><div className="panel-head"><div><h2>Add {page} asset</h2><p>System-boundary inventory record. Authorization remains a human review decision.</p></div><Status value="PENDING_REVIEW"/></div><form className="record-grid" onSubmit={event => createAsset(event, currentAssetType)}><label>Asset identifier<input required minLength="2" value={assetForm.assetIdentifier} onChange={event => setAssetForm({...assetForm, assetIdentifier: event.target.value})} placeholder={page === 'software' ? 'Product or package ID' : 'Serial number or asset tag'}/></label><label>Name<input required minLength="2" value={assetForm.name} onChange={event => setAssetForm({...assetForm, name: event.target.value})} placeholder={page === 'software' ? 'Product name' : 'Device name'}/></label><label>{page === 'software' ? 'Publisher' : 'Manufacturer'}<input value={assetForm.publisherOrManufacturer} onChange={event => setAssetForm({...assetForm, publisherOrManufacturer: event.target.value})}/></label><label>{page === 'software' ? 'Version' : 'Model'}<input value={assetForm.versionOrModel} onChange={event => setAssetForm({...assetForm, versionOrModel: event.target.value})}/></label><label>Owner<input value={assetForm.owner} onChange={event => setAssetForm({...assetForm, owner: event.target.value})} placeholder="Responsible team or person"/></label><label>System role<input value={assetForm.systemRole} onChange={event => setAssetForm({...assetForm, systemRole: event.target.value})} placeholder="e.g., endpoint, collaboration, backup"/></label><label>Authorization<select value={assetForm.authorizationStatus} onChange={event => setAssetForm({...assetForm, authorizationStatus: event.target.value})}>{['AUTHORIZED','PENDING_REVIEW','RESTRICTED','RETIRED'].map(value => <option key={value}>{value}</option>)}</select></label><label>Lifecycle<select value={assetForm.lifecycleStatus} onChange={event => setAssetForm({...assetForm, lifecycleStatus: event.target.value})}>{['ACTIVE','MAINTENANCE','RETIRED','DISPOSED'].map(value => <option key={value}>{value}</option>)}</select></label><label className="check-label"><input type="checkbox" checked={assetForm.cuiInScope} onChange={event => setAssetForm({...assetForm, cuiInScope: event.target.checked})}/> CUI in system boundary</label><label>Last reviewed<input type="date" value={assetForm.lastReviewedAt} onChange={event => setAssetForm({...assetForm, lastReviewedAt: event.target.value})}/></label><label>Evidence reference<textarea value={assetForm.evidenceReference} onChange={event => setAssetForm({...assetForm, evidenceReference: event.target.value})} placeholder="Inventory scan, ticket, or review evidence"/></label><label>Notes<textarea value={assetForm.notes} onChange={event => setAssetForm({...assetForm, notes: event.target.value})} placeholder="Scope, location, or handling notes"/></label><button>Save {page} asset</button></form></section><section className="panel table-panel"><div className="panel-head"><div><h2>{page === 'software' ? 'Software' : 'Hardware'} inventory</h2><p>{filteredAssets(currentAssetType).length} system-boundary records.</p></div></div>{filteredAssets(currentAssetType).length ? <table><thead><tr><th>Asset</th><th>{page === 'software' ? 'Publisher / version' : 'Manufacturer / model'}</th><th>Owner</th><th>Authorization</th><th>CUI</th><th>Reviewed</th></tr></thead><tbody>{filteredAssets(currentAssetType).map(item => <tr key={item.id}><td><b>{item.name}</b><small>{item.assetIdentifier}</small></td><td>{item.publisherOrManufacturer || '—'}<small>{item.versionOrModel || '—'}</small></td><td>{item.owner || '—'}</td><td><Status value={item.authorizationStatus}/></td><td>{item.cuiInScope ? 'In scope' : 'Out of scope'}</td><td>{fmt(item.lastReviewedAt)}</td></tr>)}</tbody></table> : <Empty title={`No ${page} assets`} body={`Add reviewed ${page} assets that support or reside within the CMMC system boundary.`}/>}</section></>}
      {page === 'accounts' && <section className="sync-panel"><div><b>Microsoft Entra synchronization</b><small>{accounts.filter(item => item.source?.startsWith('Microsoft Graph')).length} of {accounts.length} records synchronized from Microsoft Graph. Reads users and active directory-role memberships; it preserves assessor-entered MFA and review data.</small></div><button className="sync-button" onClick={() => syncFromTenant('accounts')}>↻ Sync from tenant</button></section>}
      {['software','hardware'].includes(page) && <section className="sync-panel"><div><b>Microsoft Intune synchronization</b><small>{filteredAssets(currentAssetType).filter(item => item.source?.startsWith('Microsoft Graph')).length} displayed records synchronized from Microsoft Graph. Reads managed devices, detected apps, and the Intune managed-app catalog; it never changes tenant assets.</small></div><button className="sync-button" onClick={() => syncFromTenant('inventory')}>↻ Sync from tenant</button></section>}
      {page === 'changes' && <><section className="panel record-form-panel"><div className="panel-head"><div><h2>Record planned change</h2><p>Approval-driven local record. It can be linked to inventory and POA&M work, but never executes a tenant change.</p></div><Status value="DRAFT"/></div><form className="record-grid" onSubmit={createChange}><label>Change title<input required minLength="3" value={changeForm.title} onChange={event => setChangeForm({...changeForm, title: event.target.value})} placeholder="Describe the planned change"/></label><label>Owner<input value={changeForm.owner} onChange={event => setChangeForm({...changeForm, owner: event.target.value})} placeholder="Implementation owner"/></label><label>Change type<select value={changeForm.changeType} onChange={event => setChangeForm({...changeForm, changeType: event.target.value})}>{['STANDARD','NORMAL','EMERGENCY'].map(value => <option key={value}>{value}</option>)}</select></label><label>Risk level<select value={changeForm.riskLevel} onChange={event => setChangeForm({...changeForm, riskLevel: event.target.value})}>{['LOW','MEDIUM','HIGH','CRITICAL'].map(value => <option key={value}>{value}</option>)}</select></label><label>Status<select value={changeForm.status} onChange={event => setChangeForm({...changeForm, status: event.target.value})}>{['DRAFT','SUBMITTED','APPROVED','SCHEDULED','IMPLEMENTING','CLOSED','REJECTED','CANCELLED'].map(value => <option key={value}>{value}</option>)}</select></label><label>Approver<input value={changeForm.approver} onChange={event => setChangeForm({...changeForm, approver: event.target.value})} placeholder="Approver, when assigned"/></label><label>Planned start<input type="date" value={changeForm.plannedStartAt} onChange={event => setChangeForm({...changeForm, plannedStartAt: event.target.value})}/></label><label>Planned end<input type="date" value={changeForm.plannedEndAt} onChange={event => setChangeForm({...changeForm, plannedEndAt: event.target.value})}/></label><label>Linked asset<select value={changeForm.assetId} onChange={event => setChangeForm({...changeForm, assetId: event.target.value})}><option value="">No linked asset</option>{assets.map(item => <option key={item.id} value={item.id}>{item.name} · {item.assetIdentifier}</option>)}</select></label><label>Linked POA&M<select value={changeForm.poamItemId} onChange={event => setChangeForm({...changeForm, poamItemId: event.target.value})}><option value="">No linked POA&M item</option>{poam.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label><label className="wide">Description<textarea value={changeForm.description} onChange={event => setChangeForm({...changeForm, description: event.target.value})} placeholder="Scope, expected impact, and validation approach"/></label><label>Rollback plan<textarea value={changeForm.rollbackPlan} onChange={event => setChangeForm({...changeForm, rollbackPlan: event.target.value})} placeholder="Steps to safely reverse the change"/></label><label>Evidence reference<textarea value={changeForm.evidenceReference} onChange={event => setChangeForm({...changeForm, evidenceReference: event.target.value})} placeholder="Ticket, approval, test, or implementation evidence"/></label><button>Create change record</button></form></section><section className="panel table-panel"><div className="panel-head"><div><h2>Change register</h2><p>{filteredChanges.length} approval-driven records.</p></div></div>{filteredChanges.length ? <table><thead><tr><th>Change</th><th>Owner</th><th>Risk</th><th>Status</th><th>Linked record</th><th>Planned</th></tr></thead><tbody>{filteredChanges.map(item => <tr key={item.id}><td><b>{item.title}</b><small>{statusText(item.changeType)}</small></td><td>{item.owner || '—'}</td><td><Status value={item.riskLevel}/></td><td><Status value={item.status}/></td><td>{item.assetName || item.poamTitle || '—'}</td><td>{fmt(item.plannedStartAt)}</td></tr>)}</tbody></table> : <Empty title="No change records" body="Record proposed changes before implementation so approvals, rollback planning, and evidence remain traceable."/>}</section></>}
      {page === 'screenshots' && <><section className="panel record-form-panel"><div className="panel-head"><div><h2>Capture screenshot evidence</h2><p>Select a screen, window, or browser tab when prompted. After you select a source, one still image is saved. Screen sharing stops before upload begins.</p></div><Status value="USER_APPROVED"/></div><div className="record-grid"><label>Evidence title<input required minLength="3" value={screenshotForm.title} onChange={event => setScreenshotForm({...screenshotForm, title: event.target.value})} placeholder="e.g., Conditional Access policy review"/></label><label>CMMC objective <small>Optional</small><input value={screenshotForm.objectiveIdentifier} onChange={event => setScreenshotForm({...screenshotForm, objectiveIdentifier: event.target.value})} placeholder="e.g., AC.L2-3.1.1[a]"/></label><label>Captured by<input value={session.username} readOnly/></label><label>Related record type<select value={screenshotForm.relatedRecordType} onChange={event => setScreenshotForm({...screenshotForm, relatedRecordType: event.target.value})}><option value="">No related record</option>{['ASSESSMENT','ACCOUNT','ASSET','CHANGE','POAM'].map(value => <option key={value}>{value}</option>)}</select></label><label className="wide">Related record ID <small>Optional local record ID</small><input value={screenshotForm.relatedRecordId} onChange={event => setScreenshotForm({...screenshotForm, relatedRecordId: event.target.value})} placeholder="Local record UUID, if linking to a register item"/></label><label className="wide">Capture notes<textarea value={screenshotForm.notes} onChange={event => setScreenshotForm({...screenshotForm, notes: event.target.value})} placeholder="State what the screen demonstrates and the review context"/></label><label className="check-label"><input type="checkbox" checked={screenshotForm.containsCui} onChange={event => setScreenshotForm({...screenshotForm, containsCui: event.target.checked})}/> This screenshot contains CUI</label><button className="capture-button" type="button" disabled={capturing} onClick={captureScreenshot}>{capturing ? 'Waiting for capture…' : '▣ Capture screenshot'}</button></div></section><section className="panel"><div className="panel-head"><div><h2>Screenshot evidence gallery</h2><p>{screenshots.length} locally hashed capture{screenshots.length === 1 ? '' : 's'}.</p></div></div>{screenshots.length ? <div className="screenshot-grid">{screenshots.map(item => <article className="screenshot-card" key={item.id}><a href={`/api/screenshots/${item.id}/content`} target="_blank" rel="noreferrer"><img src={`/api/screenshots/${item.id}/content`} alt={item.title}/></a><div><b>{item.title}</b><small>{item.objectiveIdentifier || 'No objective linked'} · {fmt(item.capturedAt)}</small><small>SHA-256 {item.sha256.slice(0, 16)}… · {Math.ceil(item.byteSize / 1024)} KB</small>{item.containsCui && <Status value="CUI"/>}</div></article>)}</div> : <Empty title="No screenshots captured" body="Enter evidence metadata, then use Capture screenshot to select the exact screen, window, or tab to retain."/>}</section></>}
    </main>
  </div>;
}
createRoot(document.getElementById('root')).render(<App/>);

import React, { useEffect, useState } from 'react';
import './poam.css';

const outcomes = ['NOT_STARTED', 'IN_REVIEW', 'SUPPORTED', 'GAP', 'NOT_APPLICABLE'];
const label = value => value.replaceAll('_', ' ');
const draftOf = review => ({ ...review, categories: review.requiredEventCategories.join('\n') });
const timestamp = value => new Date(value + 'Z').toLocaleString();
export default function AuditWorkspace({ screenshots, onDirty, onAuthExpired, onRecordsChanged, onOpenPoam }) {
  const [rows, setRows] = useState([]);
  const [run, setRun] = useState(() => new URLSearchParams(location.hash.split('?')[1]).get('run') || '');
  const [detail, setDetail] = useState(null);
  const [draft, setDraft] = useState(null);
  const [status, setStatus] = useState('');
  const [overdue, setOverdue] = useState(false);
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [gap, setGap] = useState({ title: '', identifier: '', targetDate: '', key: crypto.randomUUID() });
  const dirty = !!draft && !!detail && JSON.stringify(draft) !== JSON.stringify(draftOf(detail.review));
  const gapDirty = !!(gap.title || gap.identifier || gap.targetDate);
  useEffect(() => { onDirty(dirty || gapDirty || busy); return () => onDirty(false); }, [dirty, gapDirty, busy]);
  useEffect(() => {
    const guard = event => { if (dirty || gapDirty || busy) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', guard); return () => window.removeEventListener('beforeunload', guard);
  }, [dirty, gapDirty, busy]);
  async function request(path, options) {
    const response = await fetch(path, options);
    if (response.status === 401) { onAuthExpired(); throw new Error('Please sign in again.'); }
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.map(item => item.msg).join('; ') || 'Request failed.');
    return data;
  }
  const base = `/api/assessments/${encodeURIComponent(run)}/audit-review`;
  async function refresh() { const data = await request('/api/audit-reviews'); setRows(data.items); }
  useEffect(() => { refresh().catch(err => setError(err.message)); }, []);
  useEffect(() => {
    let cancelled = false; setDetail(null); setDraft(null); setError(''); setMessage('');
    if (run) request(base).then(data => { if (!cancelled) { setDetail(data); setDraft(draftOf(data.review)); } }).catch(err => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [run]);
  function select(value) {
    if (value === run || busy || ((dirty || gapDirty) && !window.confirm('Discard unsaved audit review changes?'))) return;
    setRun(value); setGap({ title: '', identifier: '', targetDate: '', key: crypto.randomUUID() });
    window.history.replaceState(null, '', '#audit?' + new URLSearchParams({ run: value }));
  }
  function edit(key, value) { setDraft(previous => ({ ...previous, [key]: value })); }
  async function reload() {
    if ((dirty || gapDirty) && !window.confirm('Discard drafts and reload the saved review?')) return;
    setBusy(true); setError(''); setMessage('');
    try { const data = await request(base); setDetail(data); setDraft(draftOf(data.review)); setGap({ title: '', identifier: '', targetDate: '', key: crypto.randomUUID() }); await refresh(); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  async function save(event) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('');
    try {
      const data = await request(base, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        expected_revision: detail.review.revision, review_owner: draft.reviewOwner, retention_days: draft.retentionDays === '' ? null : draft.retentionDays,
        review_frequency: draft.reviewFrequency, required_event_categories: draft.categories.split('\n').map(s => s.trim()).filter(Boolean),
        status: draft.status, notes: draft.notes, next_review_date: draft.nextReviewDate || null,
        resources: draft.resources.map(({ kind, id }) => ({ kind, id })) }) });
      setDetail(data); setDraft(draftOf(data.review));
      if (data.review.status !== 'GAP') setGap({ title: '', identifier: '', targetDate: '', key: crypto.randomUUID() });
      setMessage('Audit review saved.'); await refresh();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  async function createGap(event) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('');
    try {
      await request(base + '/poam', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        expected_revision: detail.review.revision, request_key: gap.key, identifier: gap.identifier, title: gap.title, target_date: gap.targetDate || null }) });
      setGap({ title: '', identifier: '', targetDate: '', key: crypto.randomUUID() });
      const data = await request(base); setDetail(data); setDraft(draftOf(data.review)); setMessage('Linked POA&M created.'); await onRecordsChanged();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  function attachment(ref) {
    const selected = draft.resources.some(item => item.id === ref.id && item.kind === ref.kind);
    return <label className="poam-check" key={ref.kind + ref.id}><input type="checkbox" checked={selected} disabled={!selected && draft.resources.length >= 100} onChange={e => edit('resources', e.target.checked ? [...draft.resources, ref] : draft.resources.filter(item => !(item.id === ref.id && item.kind === ref.kind)))}/>{ref.label}{ref.containsCui ? ' · Contains CUI' : ''}</label>;
  }
  const visible = rows.filter(item => (!status || status === item.status) && (!overdue || item.overdue) && `${item.tenantId} ${item.reviewOwner} ${item.runId}`.toLowerCase().includes(search.toLowerCase()));
  return <div className="poam-workspace audit-workspace"><section className="panel poam-panel"><h2>Audit review queue</h2><p>Review audit-log coverage, retention, and monitoring evidence for each assessment. Conclusions do not automatically change objective decisions.</p>
    <div className="record-grid"><label>Search audit reviews<input value={search} onChange={e => setSearch(e.target.value)} placeholder="Owner, tenant, or run ID"/></label><label>Audit outcome filter<select value={status} onChange={e => setStatus(e.target.value)}><option value="">All outcomes</option>{outcomes.map(s => <option key={s} value={s}>{label(s)}</option>)}</select></label></div>
    <label className="poam-check"><input type="checkbox" checked={overdue} onChange={e => setOverdue(e.target.checked)}/> Overdue reviews only</label><p>Overdue means the next review date is before today in UTC. Set the next date explicitly after each review.</p>
    <p>{visible.length} matching reviews</p><div className="poam-register">{visible.map(item => <button key={item.runId} aria-pressed={run === item.runId} onClick={() => select(item.runId)}><strong>{timestamp(item.startedAt)} · {item.runId.slice(0, 8)}</strong><span>{item.tenantId}</span><span>{item.reviewOwner || 'Unassigned'} · {label(item.status)} · Next {item.nextReviewDate || 'not scheduled'}{item.overdue ? ' · Overdue' : ''}</span></button>)}</div>{!visible.length && <p>No reviews match. Create an assessment run to start a review.</p>}
    <button disabled={busy} onClick={() => refresh().catch(err => setError(err.message))}>Refresh queue</button></section>
    {error && <div role="alert" className="alert error-alert">{error}</div>}{message && <p role="status">{message}</p>}{run && !detail && !error && <p role="status">Loading audit review…</p>}
    {detail && draft && <section className="panel poam-panel"><h2>Audit evidence review</h2><p>Assessment {detail.runId} · Tenant {detail.tenantId}</p>
      <form onSubmit={save}><fieldset disabled={busy}><div className="record-grid">
        <label>Review owner<input maxLength={200} value={draft.reviewOwner} onChange={e => edit('reviewOwner', e.target.value)}/></label>
        <label>Next review date<input type="date" value={draft.nextReviewDate || ''} onChange={e => edit('nextReviewDate', e.target.value)}/></label>
        <label>Retention period (days)<input type="number" min={0} max={36500} value={draft.retentionDays ?? ''} onChange={e => edit('retentionDays', e.target.value === '' ? '' : Number(e.target.value))}/></label>
        <label>Review frequency<input maxLength={100} value={draft.reviewFrequency} onChange={e => edit('reviewFrequency', e.target.value)} placeholder="For example: monthly"/></label>
        <label>Required event categories<textarea value={draft.categories} onChange={e => edit('categories', e.target.value)} placeholder="One category per line"/></label>
        <label>Review conclusion<select value={draft.status} onChange={e => edit('status', e.target.value)}>{outcomes.map(s => <option key={s} value={s}>{label(s)}</option>)}</select></label>
        <label className="wide">Review notes and rationale<textarea maxLength={20000} value={draft.notes} onChange={e => edit('notes', e.target.value)}/></label>
      </div><p>A conclusion requires an owner and rationale. Supported also requires evidence, retention, frequency, and required event categories.</p>
      <h3>Attached evidence</h3>{draft.resources.map(ref => <div key={ref.kind + ref.id}><a href={ref.url} target="_blank" rel="noreferrer">{ref.label}</a><small>{ref.kind} · SHA-256 {ref.sha256}</small><button type="button" onClick={() => edit('resources', draft.resources.filter(item => !(item.id === ref.id && item.kind === ref.kind)))}>Remove {ref.label}</button></div>)}{!draft.resources.length && <p>No evidence attached.</p>}
      <details><summary>Select evidence</summary><p>Discovery evidence is limited to this assessment run. Verify that selected screenshots support this review.</p><h4>Discovery evidence</h4>{detail.evidence.map(attachment)}<h4>Screenshot evidence</h4>{screenshots.map(shot => attachment({ kind: 'SCREENSHOT', id: shot.id, label: shot.title, sha256: shot.sha256, containsCui: shot.containsCui, url: `/api/screenshots/${shot.id}/content` }))}</details>
      <div className="poam-actions"><button disabled={!dirty}>Save audit review</button><button type="button" onClick={() => { setDraft(draftOf(detail.review)); setError(''); setMessage(''); }}>Discard review changes</button><button type="button" onClick={reload}>Reload saved review</button></div></fieldset></form>
      <h3>Linked POA&M items</h3>{detail.poam.map(item => <p key={item.id}><button disabled={busy} onClick={() => onOpenPoam(item.id)}>{item.title}</button> · {label(item.status)}</p>)}{!detail.poam.length && <p>No gaps linked to this audit review.</p>}
      {detail.review.status === 'GAP' ? <form onSubmit={createGap}><fieldset disabled={busy || dirty}><h3>Create an audit gap</h3><div className="record-grid"><label>Gap title<input required minLength={3} maxLength={240} value={gap.title} onChange={e => setGap({ ...gap, title: e.target.value })}/></label><label>Audit objective<select required value={gap.identifier} onChange={e => setGap({ ...gap, identifier: e.target.value })}><option value="">Select an objective</option>{detail.objectives.map(item => <option key={item.identifier} value={item.identifier}>{item.identifier} · {item.statement}</option>)}</select></label><label>Gap target date<input type="date" value={gap.targetDate} onChange={e => setGap({ ...gap, targetDate: e.target.value })}/></label></div><p>The gap inherits the saved review owner and rationale. Manage milestones and closure in POA&M.</p><button>Create linked POA&M</button><button type="button" onClick={() => setGap({ title: '', identifier: '', targetDate: '', key: crypto.randomUUID() })}>Discard gap draft</button></fieldset>{dirty && <p>Save or discard review changes before creating a gap.</p>}</form> : <p>Save a Gap conclusion to create a linked POA&M item.</p>}
      <h3>Review history</h3>{!detail.history.length && <p>No revisions yet. Existing review notes will be preserved on first save.</p>}{detail.history.map(row => <details key={row.revision}><summary>{row.revision === 0 ? 'Original baseline' : `Revision ${row.revision}`} · {row.recordedBy} · {timestamp(row.recordedAt)}</summary><p>{row.snapshot.reviewOwner || 'Unassigned'} · {label(row.snapshot.status)}</p><p>Retention: {row.snapshot.retentionDays ?? 'Not set'} days · Frequency: {row.snapshot.reviewFrequency || 'Not set'} · Next review: {row.snapshot.nextReviewDate || 'Not scheduled'}</p><p>Required events: {row.snapshot.requiredEventCategories.join(', ') || 'Not set'}</p><p style={{ whiteSpace: 'pre-wrap' }}>{row.snapshot.notes}</p>{row.snapshot.resources.map(ref => <p key={ref.kind + ref.id}><a href={ref.url} target="_blank" rel="noreferrer">{ref.label}</a><small>SHA-256 {ref.sha256}</small></p>)}</details>)}
    </section>}
  </div>;
}

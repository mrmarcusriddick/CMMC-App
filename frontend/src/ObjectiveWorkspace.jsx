import React, { useEffect, useRef, useState } from 'react';
import './objectives.css';

const text = value => (value || '').replaceAll('_', ' ').toLowerCase();
const date = value => value ? new Date(value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`).toLocaleString() : '—';
const key = item => `${item.kind}:${item.id}`;
const fromHash = () => new URLSearchParams(window.location.hash.split('?')[1] || '');

export default function ObjectiveWorkspace({ runs, onAuthExpired, onDirty, onRecordsChanged, onOpenPoam }) {
  const [runId, setRunId] = useState(() => fromHash().get('run') || runs[0]?.id || '');
  const [identifier, setIdentifier] = useState(() => fromHash().get('objective') || '');
  const [catalog, setCatalog] = useState(null);
  const [detail, setDetail] = useState(null);
  const [draft, setDraft] = useState(null);
  const [search, setSearch] = useState('');
  const [domain, setDomain] = useState('');
  const [status, setStatus] = useState('');
  const [kind, setKind] = useState('SCREENSHOT');
  const [resourceQuery, setResourceQuery] = useState('');
  const [resources, setResources] = useState({ items: [] });
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [reload, setReload] = useState(0);
  const [gap, setGap] = useState({ title: '', description: '', owner: '', targetDate: '' });
  const requestKey = useRef(crypto.randomUUID());
  const dirty = !!(draft && detail && JSON.stringify(draft) !== JSON.stringify(detail.review));
  const base = `/api/assessments/${encodeURIComponent(runId)}/objectives`;
  const endpoint = `${base}/${encodeURIComponent(identifier)}`;
  useEffect(() => {
    onDirty(dirty || busy);
    return () => onDirty(false);
  }, [dirty, busy, onDirty]);

  async function api(url, options = {}) {
    const response = await fetch(url, options);
    if (response.status === 401) { onAuthExpired(); throw new Error('Your session expired. Please sign in again.'); }
    const data = await response.json();
    if (!response.ok) throw new Error(Array.isArray(data.detail) ? data.detail.map(item => item.msg).join(' ') : data.detail || 'Request failed.');
    return data;
  }
  useEffect(() => { if (!runId && runs.length) setRunId(runs[0].id); }, [runs, runId]);
  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    setCatalog(null); setError('');
    api(base, { signal: controller.signal }).then(setCatalog).catch(err => { if (err.name !== 'AbortError') setError(err.message); });
    return () => controller.abort();
  }, [runId, reload]);
  useEffect(() => {
    setDetail(null); setDraft(null); setMessage(''); setError(''); setGap({ title: '', description: '', owner: '', targetDate: '' });
    requestKey.current = crypto.randomUUID();
    if (!runId || !identifier) { setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true);
    api(endpoint, { signal: controller.signal }).then(data => { setDetail(data); setDraft(data.review); })
      .catch(err => { if (err.name !== 'AbortError') setError(err.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [runId, identifier, reload]);
  useEffect(() => {
    if (!runId || !identifier) return;
    const controller = new AbortController();
    setResources({ items: [] });
    api(`${endpoint}/resources?${new URLSearchParams({ kind, q: resourceQuery })}`, { signal: controller.signal })
      .then(setResources).catch(err => { if (err.name !== 'AbortError') setError(err.message); });
    return () => controller.abort();
  }, [runId, identifier, kind, resourceQuery]);
  useEffect(() => {
    const handler = event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  function select(run, objective) {
    if (busy || (dirty && !window.confirm('Discard the unsaved review changes?'))) return;
    setRunId(run); setIdentifier(objective); setResourceQuery('');
    window.history.replaceState(null, '', `#objectives?${new URLSearchParams({ run, objective })}`);
  }
  function edit(field, value) { setDraft(current => ({ ...current, [field]: value })); setMessage(''); }
  function attach(item) {
    if (!draft.resources.some(ref => key(ref) === key(item))) edit('resources', [...draft.resources, item]);
  }
  async function save(event) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('');
    try {
      const result = await api(`${endpoint}/review`, { method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected_revision: draft.revision, owner: draft.owner, status: draft.status,
          decision: draft.decision, notes: draft.notes, resources: draft.resources.map(({ kind, id }) => ({ kind, id })) }) });
      setDraft(result); setDetail(current => ({ ...current, review: result, history: [result, ...current.history] }));
      setCatalog(current => current ? ({ ...current, items: current.items.map(item => item.identifier === identifier ? { ...item, review: result } : item) }) : current);
      setMessage(`Review revision ${result.revision} saved. Technical findings are unchanged.`);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  async function createGap(event) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('');
    try {
      await api(`${endpoint}/poam`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        request_key: requestKey.current, expected_revision: detail.review.revision, title: gap.title,
        description: gap.description, owner: gap.owner || detail.review.owner, target_date: gap.targetDate ? `${gap.targetDate}T12:00:00Z` : null,
      }) });
      const updated = await api(endpoint);
      setDetail(updated); setDraft(updated.review); setGap({ title: '', description: '', owner: '', targetDate: '' });
      requestKey.current = crypto.randomUUID(); setMessage('Linked POA&M item created.');
      await onRecordsChanged();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  const items = (catalog?.items || []).filter(item => (!domain || item.domain === domain) && (!status || item.review.status === status)
    && `${item.identifier} ${item.statement} ${item.practiceTitle} ${item.review.owner}`.toLowerCase().includes(search.toLowerCase()));
  return <section className="objective-workspace">
    <div className="panel objective-context"><label>Assessment run<select aria-label="Assessment run" value={runId} disabled={busy} onChange={event => select(event.target.value, '')}>
      <option value="">Select a run</option>{runs.map(run => <option key={run.id} value={run.id}>{date(run.startedAt)} · {run.tenantId} · {run.frameworkVersion ? `v${run.frameworkVersion}` : 'Unverified seed'} · {run.id.slice(0, 8)}</option>)}
    </select></label><p>Reviews belong to the selected assessment run. Each save records the signed-in operator and preserves the previous revision.</p></div>
    {!runs.length && <div className="panel objective-context">Run an assessment first to begin reviewing its objectives.</div>}
    {error && <div className="alert error-alert" role="alert">{error} <button type="button" disabled={busy} onClick={() => { if (!dirty || window.confirm('Discard unsaved changes and reload?')) setReload(value => value + 1); }}>Reload objective</button></div>}
    {message && <div className="alert success-alert" role="status">{message}</div>}
    {runId && <div className="objective-layout"><aside className="panel objective-browser">
      <h2>Objectives</h2><label>Search objectives<input value={search} onChange={event => setSearch(event.target.value)} placeholder="Identifier, wording, or owner"/></label>
      <div className="objective-filters"><label>Domain<select value={domain} onChange={event => setDomain(event.target.value)}><option value="">All domains</option>{[...new Set(catalog?.items.map(item => item.domain))].sort().map(value => <option key={value}>{value}</option>)}</select></label>
      <label>Review status<select value={status} onChange={event => setStatus(event.target.value)}><option value="">All statuses</option>{['NOT_STARTED', 'IN_REVIEW', 'COMPLETE'].map(value => <option value={value} key={value}>{text(value)}</option>)}</select></label></div>
      <p>{catalog ? `${items.length} of ${catalog.items.length} objectives` : 'Loading objectives…'}</p>
      <div className="objective-list">{items.map(item => <button key={item.identifier} type="button" disabled={busy} aria-current={identifier === item.identifier ? 'true' : undefined} onClick={() => select(runId, item.identifier)}>
        <b>{item.identifier}</b><span>{item.statement}</span><small>{text(item.review.status)} · {text(item.review.decision)}</small></button>)}</div>
      {catalog && !items.length && <p>No objectives match these filters.</p>}
    </aside><article className="objective-detail">
      {!detail && <div className="panel objective-context">{loading ? 'Loading objective…' : 'Select an objective to review its requirements and evidence.'}</div>}
      {detail && draft && <>
        {!!detail.rereviewRequests?.length && <p role="status" className="alert">A linked gap has closed. Review its closure evidence and save a new completed review. Your previous decision remains unchanged.</p>}
        <section className="panel objective-context"><span className="eyebrow">{detail.framework.version ? `CMMC v${detail.framework.version}` : 'Unverified seed catalog'} · {text(detail.framework.status)}</span><h2>{detail.identifier}</h2><h3>{detail.practiceTitle}</h3><p className="objective-statement">{detail.statement}</p>
          {detail.practiceStatement && <details><summary>Practice requirement</summary><p>{detail.practiceStatement}</p></details>}
          {detail.framework.sourceUrl?.startsWith('https://') && <a href={detail.framework.sourceUrl} target="_blank" rel="noreferrer">Catalog source ↗</a>}
          <p>Tenant: {detail.tenantId}</p><a href={`#objectives?${new URLSearchParams({ run: runId, objective: identifier })}`}>Link to this objective</a>
        </section>
        <section className="panel objective-context"><h2>Technical findings</h2><p>Discovery signals from this run support review. Your decision is recorded separately.</p>
          {!detail.findings.length && <p>No automated finding for this objective. Review supporting evidence manually.</p>}
          {detail.findings.map(finding => <div className="objective-finding" key={finding.id}><b>{text(finding.status)}</b><p>{finding.detail}</p>{finding.evidence.map(item => <div key={item.id}><a href={item.url}>Download discovery evidence ↗</a> <button type="button" disabled={busy || draft.resources.some(ref => key(ref) === key(item))} onClick={() => attach(item)}>Attach to review</button></div>)}</div>)}
        </section>
        <form className="panel objective-context" onSubmit={save}><h2>Reviewer decision</h2><p>Revision {draft.revision} · {dirty ? 'Unsaved changes' : 'No unsaved changes'}</p><fieldset disabled={busy}><div className="record-grid">
          <label>Owner<input maxLength={200} value={draft.owner} onChange={event => edit('owner', event.target.value)}/></label>
          <label>Review status<select value={draft.status} onChange={event => edit('status', event.target.value)}>{['NOT_STARTED', 'IN_REVIEW', 'COMPLETE'].map(value => <option key={value} value={value}>{text(value)}</option>)}</select></label>
          <label>Decision<select value={draft.decision} onChange={event => edit('decision', event.target.value)}>{['NOT_ASSESSED', 'MET', 'NOT_MET', 'NOT_APPLICABLE'].map(value => <option key={value} value={value}>{text(value)}</option>)}</select></label>
          <label className="wide">Review notes and rationale<textarea maxLength={20000} value={draft.notes} onChange={event => edit('notes', event.target.value)} placeholder="Explain what the evidence demonstrates and any remaining gaps."/></label>
        </div><h3>Attached evidence and records</h3><p>Attachments are saved with the review. Record labels and evidence hashes are preserved in each revision.</p>
          {!draft.resources.length && <p>No resources attached.</p>}{draft.resources.map(item => <div className="objective-resource" key={key(item)}><div><b>{item.label}</b><small>{text(item.kind)}{item.containsCui ? ' · Contains CUI' : ''}</small>{item.sha256 && <code>SHA-256 {item.sha256}</code>}{item.url && <a href={item.url} target="_blank" rel="noreferrer">Open evidence ↗</a>}</div><button type="button" onClick={() => edit('resources', draft.resources.filter(ref => key(ref) !== key(item)))}>Remove attachment</button></div>)}
          <details className="objective-attach"><summary>Attach supporting evidence or records</summary><div className="objective-filters"><label>Resource type<select value={kind} onChange={event => setKind(event.target.value)}>{['SCREENSHOT', 'DISCOVERY', 'ACCOUNT', 'ASSET', 'CHANGE'].map(value => <option key={value}>{value}</option>)}</select></label><label>Search resources<input value={resourceQuery} onChange={event => setResourceQuery(event.target.value)}/></label></div>
            <p>Discovery evidence is limited to this run and objective. Other resources come from the local workspace; confirm their relevance before attaching.</p>
            {resources.items.map(item => <div className="objective-resource" key={key(item)}><span>{item.label}{item.containsCui ? ' · Contains CUI' : ''}</span><button type="button" disabled={draft.resources.some(ref => key(ref) === key(item))} onClick={() => attach(item)}>Attach</button></div>)}
            {!resources.items.length && <p>No matching resources.</p>}{resources.hasMore && <p>Showing 100 matches. Narrow your search to find more.</p>}
          </details><button className="objective-primary" type="submit" disabled={!dirty}>{busy ? 'Saving…' : 'Save review'}</button></fieldset>
        </form>
        <section className="panel objective-context"><h2>Linked POA&M items</h2>{detail.poam.map(item => <div className="objective-resource" key={item.id}><div><button onClick={() => onOpenPoam(item.id)}>{item.title}</button><small>{text(item.status)} · {item.owner || 'Unassigned'} · Due {item.targetDate ? date(item.targetDate) : 'not set'}</small><small>Record {item.id}</small></div></div>)}{!detail.poam.length && <p>No linked POA&M items.</p>}
          {detail.review.decision === 'NOT_MET' ? <form onSubmit={createGap}><fieldset disabled={busy || dirty}><h3>Create a gap item</h3><div className="record-grid"><label>POA&M title<input required minLength={3} maxLength={240} value={gap.title} onChange={event => setGap({ ...gap, title: event.target.value })}/></label><label>Gap owner<input maxLength={200} value={gap.owner} placeholder={detail.review.owner} onChange={event => setGap({ ...gap, owner: event.target.value })}/></label><label>Target date<input type="date" value={gap.targetDate} onChange={event => setGap({ ...gap, targetDate: event.target.value })}/></label><label className="wide">Gap description<textarea value={gap.description} maxLength={20000} onChange={event => setGap({ ...gap, description: event.target.value })}/></label></div><button className="objective-primary" type="submit">Create linked POA&M</button></fieldset>{dirty && <p>Save the review before creating a gap item.</p>}</form> : <p>Save a Not met decision to create a linked gap item.</p>}
        </section>
        <section className="panel objective-context"><h2>Review history</h2>{!detail.history.length && <p>No review revisions yet.</p>}{detail.history.map(item => <details key={item.revision} className="objective-history"><summary>Revision {item.revision} · {text(item.status)} · {text(item.decision)} · {date(item.recordedAt)}</summary><p>Recorded by {item.recordedBy} · Owner: {item.owner || 'Unassigned'}</p><p className="objective-notes">{item.notes || 'No notes.'}</p><ul>{item.resources.map(ref => <li key={key(ref)}>{ref.label} ({text(ref.kind)}){ref.sha256 && <code>SHA-256 {ref.sha256}</code>}</li>)}</ul></details>)}</section>
      </>}
    </article></div>}
  </section>;
}

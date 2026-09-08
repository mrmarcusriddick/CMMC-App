import React, { useEffect, useState } from 'react';
import './poam.css';

const statuses = ['OPEN', 'IN_PROGRESS', 'BLOCKED', 'COMPLETE', 'CLOSED'];
const label = value => value.replaceAll('_', ' ');
const blank = () => ({ title: '', description: '', owner: '', status: 'OPEN', targetDate: '', milestones: [], evidenceReference: '', closureNotes: '', screenshots: [], findingId: '' });
export default function PoamWorkspace({ screenshots, onDirty, onRecordsChanged, onAuthExpired, onOpenObjective }) {
  const [items, setItems] = useState([]);
  const [id, setId] = useState(() => new URLSearchParams(location.hash.split('?')[1]).get('id') || '');
  const [detail, setDetail] = useState(null);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('');
  const [overdue, setOverdue] = useState(false);
  const dirty = !!draft && JSON.stringify(draft) !== JSON.stringify(detail);
  useEffect(() => { onDirty(dirty); return () => onDirty(false); }, [dirty]);
  useEffect(() => {
    const handler = event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', handler); return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);
  async function request(url, options) {
    const response = await fetch(url, options);
    if (response.status === 401) { onAuthExpired(); throw new Error('Please sign in again.'); }
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.map(item => item.msg).join('; ') || 'Request failed.');
    return data;
  }
  async function refresh() { setItems((await request('/api/poam/register')).items); }
  useEffect(() => { refresh().catch(err => setError(err.message)); }, []);
  useEffect(() => {
    let cancelled = false;
    setDetail(null); setDraft(null); setError(''); setMessage('');
    if (id === 'new') { const value = blank(); setDetail(value); setDraft(value); }
    else if (id) request(`/api/poam/${encodeURIComponent(id)}`).then(data => { if (!cancelled) { setDetail(data); setDraft(data); } }).catch(err => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [id]);
  function select(value) {
    if (busy || (dirty && !window.confirm('Discard unsaved POA&M changes?'))) return;
    setId(value); window.history.replaceState(null, '', `#poam${value ? '?' + new URLSearchParams({ id: value }) : ''}`);
  }
  function change(key, value) { setDraft(previous => ({ ...previous, [key]: value })); }
  async function reloadSaved() {
    if (dirty && !window.confirm('Discard your draft and reload the saved gap?')) return;
    setBusy(true); setError(''); setMessage('');
    try { const data = await request(`/api/poam/${id}`); setDetail(data); setDraft(data); await refresh(); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  async function save(event) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('');
    const creating = id === 'new';
    const payload = { title: draft.title, description: draft.description, owner: draft.owner, status: draft.status,
      target_date: draft.targetDate ? `${draft.targetDate.slice(0, 10)}T12:00:00Z` : null,
      evidence_reference: draft.evidenceReference, milestones: creating ? draft.milestones.map(item => item.title) : draft.milestones,
      ...(creating ? { finding_id: draft.findingId || null } : { expected_revision: detail.revision, closure_notes: draft.closureNotes, screenshot_ids: draft.screenshots.map(item => item.id) }) };
    try {
      const data = await request(creating ? '/api/poam' : `/api/poam/${id}`, { method: creating ? 'POST' : 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (creating) { setId(data.id); window.history.replaceState(null, '', `#poam?${new URLSearchParams({ id: data.id })}`); }
      else { setDetail(data); setDraft(data); setMessage('POA&M changes saved.'); }
      await refresh(); await onRecordsChanged();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  const visible = items.filter(item => (!filter || item.status === filter) && (!overdue || item.overdue) && `${item.title} ${item.owner} ${item.identifier || ''}`.toLowerCase().includes(search.toLowerCase()));
  return <div className="poam-workspace">
    <section className="panel poam-panel"><div className="panel-head"><div><h2>Plans of action & milestones</h2><p>Assign work, track milestones, and document closure.</p></div><button disabled={busy} onClick={() => select('new')}>New POA&M</button></div>
      <div className="record-grid"><label>Search gaps<input value={search} onChange={e => setSearch(e.target.value)}/></label><label>Filter status<select value={filter} onChange={e => setFilter(e.target.value)}><option value="">All statuses</option>{statuses.map(s => <option key={s} value={s}>{label(s)}</option>)}</select></label></div>
      <label className="poam-check"><input type="checkbox" checked={overdue} onChange={e => setOverdue(e.target.checked)}/> Overdue only (UTC)</label>
      <p>{visible.length} matching gaps</p><div className="poam-register">{visible.map(item => <button key={item.id} aria-pressed={id === item.id} onClick={() => select(item.id)}><strong>{item.title}</strong><span>{item.identifier || 'Standalone'} · {item.owner || 'Unassigned'} · {label(item.status)}</span><span>{item.overdue ? 'Overdue · ' : ''}Due {item.targetDate?.slice(0, 10) || 'not set'}</span></button>)}</div>
      {!visible.length && <p>No gaps match these filters. Create a gap here or from an objective marked Not met.</p>}
    </section>
    {error && <div role="alert" className="alert error-alert">{error}</div>}{message && <p role="status">{message}</p>}
    {id && !draft && !error && <p role="status">Loading gap…</p>}
    {draft && <section className="panel poam-panel"><h2>{id === 'new' ? 'Create POA&M item' : 'POA&M detail'}</h2>
      {detail.identifier && <p>Linked objective: <button disabled={busy} onClick={() => { if (!dirty || window.confirm('Discard unsaved POA&M changes?')) onOpenObjective(detail.runId, detail.identifier); }}>{detail.identifier}</button></p>}
      {detail.rereviewPending && <p role="status" className="alert">A closure of this gap awaits objective re-review. Complete a new review of the linked objective to acknowledge it. Its decision has not changed.</p>}
      <form onSubmit={save}><fieldset disabled={busy}><div className="record-grid">
        <label>Gap title<input required minLength={3} maxLength={240} value={draft.title} onChange={e => change('title', e.target.value)}/></label>
        <label>Gap owner<input maxLength={200} value={draft.owner} onChange={e => change('owner', e.target.value)}/></label>
        <label>Gap status<select value={draft.status} onChange={e => change('status', e.target.value)}>{(id === 'new' ? statuses.slice(0, 3) : statuses).map(s => <option key={s} value={s}>{label(s)}</option>)}</select></label>
        <label>Gap target date<input type="date" value={draft.targetDate?.slice(0, 10) || ''} onChange={e => change('targetDate', e.target.value)}/></label>
        {id === 'new' && <label className="wide">Linked finding ID (optional)<input maxLength={36} value={draft.findingId} onChange={e => change('findingId', e.target.value)} placeholder="Finding UUID"/></label>}
        <label className="wide">Gap description<textarea maxLength={id === 'new' ? 5000 : 20000} value={draft.description} onChange={e => change('description', e.target.value)}/></label>
      </div><h3>Milestones</h3>{draft.milestones.map((item, index) => <div className="poam-milestone" key={index}>
        {id !== 'new' && <input aria-label={`Milestone ${index + 1} complete`} type="checkbox" checked={item.complete} onChange={e => change('milestones', draft.milestones.map((m, i) => i === index ? { ...m, complete: e.target.checked } : m))}/>}
        <input aria-label={`Milestone ${index + 1} title`} required maxLength={500} value={item.title} onChange={e => change('milestones', draft.milestones.map((m, i) => i === index ? { ...m, title: e.target.value } : m))}/>
        <button type="button" aria-label={`Remove milestone ${index + 1}`} onClick={() => change('milestones', draft.milestones.filter((_, i) => i !== index))}>Remove</button></div>)}
      <button type="button" disabled={draft.milestones.length >= 30} onClick={() => change('milestones', [...draft.milestones, { title: '', complete: false }])}>Add milestone</button>
      <label>Evidence reference<textarea maxLength={5000} value={draft.evidenceReference} onChange={e => change('evidenceReference', e.target.value)} placeholder="Ticket, evidence path, or verification reference"/></label>
      {id !== 'new' && <><h3>Closure evidence</h3><p>Complete or closed gaps require an owner, finished milestones, closure notes, and an evidence reference or screenshot. Closing a linked gap requests another objective review.</p>
        <label>Closure notes<textarea maxLength={5000} value={draft.closureNotes} onChange={e => change('closureNotes', e.target.value)}/></label>
        <div className="poam-evidence">{screenshots.map(shot => <label className="poam-check" key={shot.id}><input type="checkbox" checked={draft.screenshots.some(s => s.id === shot.id)} onChange={e => change('screenshots', e.target.checked ? [...draft.screenshots, shot] : draft.screenshots.filter(s => s.id !== shot.id))}/>{shot.title}</label>)}</div>
        {draft.screenshots.map(shot => <p key={shot.id}><a href={`/api/screenshots/${shot.id}/content`} target="_blank" rel="noreferrer">{shot.title}</a>{shot.sha256 && <small>SHA-256: {shot.sha256}</small>}</p>)}
      </>}
      <div className="poam-actions"><button disabled={!dirty || busy}>{busy ? 'Saving…' : id === 'new' ? 'Create gap' : 'Save gap'}</button><button type="button" onClick={() => { setDraft(detail); setError(''); setMessage(''); }}>Discard changes</button>{id !== 'new' && <button type="button" onClick={reloadSaved}>Reload saved gap</button>}</div>
      </fieldset></form>
      {detail.history && <><h3>Change history</h3>{!detail.history.length && <p>No edits recorded yet. The original record will be preserved when first edited.</p>}{detail.history.map(row => <details key={row.revision}><summary>{row.revision === 0 ? 'Original baseline' : `Revision ${row.revision}`} · {row.recordedBy} · {new Date(row.recordedAt + 'Z').toLocaleString()}</summary><p>{row.snapshot.title} · {label(row.snapshot.status)} · {row.snapshot.owner || 'Unassigned'} · Due {row.snapshot.targetDate?.slice(0, 10) || 'not set'}</p><p>{row.snapshot.description}</p><ul>{row.snapshot.milestones.map((m, i) => <li key={i}>{m.complete ? 'Complete' : 'Pending'}: {m.title}</li>)}</ul><p>Closure: {row.snapshot.closureNotes || 'None'}</p><p>Evidence: {row.snapshot.evidenceReference || 'None'}</p>{row.snapshot.screenshots.map(s => <p key={s.id}>{s.title}<small>SHA-256: {s.sha256}</small></p>)}</details>)}</>}
    </section>}
  </div>;
}

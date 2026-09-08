import React, { useEffect, useState } from 'react';
import './summary.css';

const label = value => (value || '').replaceAll('_', ' ').toLowerCase();
const queueLabels = { all: 'All objectives', missingOwner: 'Missing owner', missingEvidence: 'No attachments', pendingDecision: 'Decision pending', reReview: 'Re-review after closure' };
const runDate = value => new Date(/[Zz]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`).toLocaleString();

export default function AssessmentSummary({ runs, onAuthExpired, onOpenObjective, onOpenPoam }) {
  const [runId, setRunId] = useState(() => new URLSearchParams(window.location.hash.split('?')[1] || '').get('run') || runs[0]?.id || '');
  const [report, setReport] = useState(null);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [domain, setDomain] = useState('');
  const [queue, setQueue] = useState('all');
  const [search, setSearch] = useState('');
  const [overdueOnly, setOverdueOnly] = useState(false);
  useEffect(() => { if (!runId && runs.length) setRunId(runs[0].id); }, [runId, runs]);
  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    setReport(null); setError('');
    fetch(`/api/assessments/${encodeURIComponent(runId)}/summary`, { signal: controller.signal }).then(async response => {
      if (response.status === 401) { onAuthExpired(); return; }
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'The assessment summary could not be loaded.');
      setReport(data);
    }).catch(err => { if (err.name !== 'AbortError') setError(err.message); });
    return () => controller.abort();
  }, [runId, refresh]);
  function chooseRun(value) {
    setRunId(value); setDomain(''); setQueue('all'); setSearch('');
    window.history.replaceState(null, '', `#summary?${new URLSearchParams({ run: value })}`);
  }
  function objectiveLink(identifier) {
    return <a href={`#objectives?${new URLSearchParams({ run: runId, objective: identifier })}`} onClick={event => {
      if (!event.ctrlKey && !event.metaKey) { event.preventDefault(); onOpenObjective(runId, identifier); }
    }}>{identifier}</a>;
  }
  const visible = (report?.objectives || []).filter(item => (!domain || item.domain === domain)
    && (queue === 'all' || report.queues[queue].includes(item.identifier))
    && `${item.identifier} ${item.statement} ${item.review.owner}`.toLowerCase().includes(search.toLowerCase()));
  const gaps = (report?.poam || []).filter(item => !overdueOnly || item.overdue);
  const t = report?.totals;
  const technical = (report?.technicalFindings || []).reduce((counts, item) => ({ ...counts, [item.status]: (counts[item.status] || 0) + 1 }), {});
  return <section className="assessment-summary">
    <section className="panel summary-panel"><label>Assessment run<select aria-label="Summary assessment run" value={runId} onChange={event => chooseRun(event.target.value)}><option value="">Select a run</option>{runs.map(run => <option key={run.id} value={run.id}>{runDate(run.startedAt)} · {run.tenantId} · {run.frameworkVersion ? `v${run.frameworkVersion}` : 'Unverified seed'} · {run.id.slice(0, 8)}</option>)}</select></label>
      <div className="summary-actions"><button onClick={() => setRefresh(value => value + 1)} disabled={!runId}>Refresh summary</button>{report && <><a href={`/api/assessments/${encodeURIComponent(runId)}/review-report.json`}>Download review JSON</a><a href={`/api/assessments/${encodeURIComponent(runId)}/review-report.md`}>Download review Markdown</a></>}</div>
      <p>Exports include all objectives in this run, the latest reviewer decisions and rationale, evidence references, technical findings, and linked POA&M items.</p>
      {!runs.length && <p>Create an assessment run to begin tracking review progress.</p>}
    </section>
    {error && <div role="alert" className="alert error-alert">{error}</div>}
    {runId && !report && !error && <p role="status">Loading assessment summary…</p>}
    {report && <>
      <section className="panel summary-panel"><span className="eyebrow">{report.framework.version ? `CMMC v${report.framework.version}` : 'Unverified seed catalog'} · {label(report.framework.status)}</span><h2>Human review progress</h2><p>Tenant: {report.tenantId}</p><p>{report.definitions.completion}</p>
        <div className="summary-metrics">{[[`${t.complete} / ${t.objectives}`, 'Reviews complete'], [`${t.completionPercent}%`, 'Review completion'], [t.inReview, 'In review'], [t.notStarted, 'Not started']].map(([value, title]) => <div key={title}><strong>{value}</strong><span>{title}</span></div>)}</div>
        <progress max={t.objectives || 1} value={t.complete} aria-label="Overall review completion"/>
        <h3>Finalized reviewer decisions</h3><div className="summary-decisions"><span>Met <b>{t.met}</b></span><span>Not met <b>{t.notMet}</b></span><span>Not applicable <b>{t.notApplicable}</b></span><span>Provisional decisions <b>{t.draftDecisions}</b></span></div><p>{report.definitions.decisions}</p>
      </section>
      <section className="panel summary-panel"><h2>Progress by domain</h2><div className="summary-table"><table><thead><tr><th>Domain</th><th>Not started</th><th>In review</th><th>Complete</th><th>Progress</th></tr></thead><tbody>{report.domains.map(item => <tr key={item.domain}><td><button aria-label={`Filter domain ${item.domain}`} onClick={() => setDomain(item.domain)}>{item.domain}</button></td><td>{item.notStarted}</td><td>{item.inReview}</td><td>{item.complete} / {item.total}</td><td><progress aria-label={`${item.domain} review completion`} max={item.total} value={item.complete}/></td></tr>)}</tbody></table></div></section>
      <section className="panel summary-panel"><h2>Review queue</h2><p>Queues may overlap. A decision is pending until the review is complete. “No attachments” means the latest review has no evidence or supporting records attached.</p>
        <div className="summary-queues">{Object.entries(queueLabels).map(([id, name]) => <button key={id} aria-pressed={queue === id} onClick={() => setQueue(id)}>{name} ({id === 'all' ? t.objectives : report.queues[id].length})</button>)}</div>
        <div className="summary-filters"><label>Search review queue<input value={search} onChange={event => setSearch(event.target.value)} placeholder="Identifier, wording, or owner"/></label><label>Queue domain<select value={domain} onChange={event => setDomain(event.target.value)}><option value="">All domains</option>{report.domains.map(item => <option key={item.domain}>{item.domain}</option>)}</select></label></div>
        <p>{visible.length} matching objectives</p><div className="summary-table summary-scroll"><table><thead><tr><th>Objective</th><th>Owner</th><th>Review status</th><th>Decision</th><th>Attachments</th></tr></thead><tbody>{visible.map(item => <tr key={item.identifier}><td>{objectiveLink(item.identifier)}<small>{item.statement}</small></td><td>{item.review.owner || 'Unassigned'}</td><td>{label(item.review.status)}</td><td>{label(item.review.decision)}{item.review.status !== 'COMPLETE' && item.review.decision !== 'NOT_ASSESSED' ? ' (provisional)' : ''}</td><td>{item.review.resources.length}</td></tr>)}</tbody></table></div>{!visible.length && <p>No objectives match this queue and filter.</p>}
      </section>
      <section className="panel summary-panel"><h2>Linked gaps and overdue actions</h2><p>{t.openGaps} open · {t.overdueGaps} overdue. Past-due dates use UTC; complete, closed, and cancelled items are excluded from overdue counts.</p><label className="summary-check"><input type="checkbox" checked={overdueOnly} onChange={event => setOverdueOnly(event.target.checked)}/> Show overdue only</label>
        <div className="summary-table"><table><thead><tr><th>Gap</th><th>Objective</th><th>Owner</th><th>Status</th><th>Target date</th></tr></thead><tbody>{gaps.map(item => <tr key={item.id}><td><button onClick={() => onOpenPoam(item.id)}>{item.title}</button>{item.overdue && <strong className="summary-overdue">Overdue</strong>}<small>{item.id}</small></td><td>{objectiveLink(item.identifier)}</td><td>{item.owner || 'Unassigned'}</td><td>{label(item.status)}</td><td>{item.targetDate?.slice(0, 10) || 'Not set'}</td></tr>)}</tbody></table></div>{!gaps.length && <p>No {overdueOnly ? 'overdue ' : ''}linked gaps.</p>}
      </section>
      <section className="panel summary-panel"><h2>Technical discovery signals</h2><p>These findings are separate from the reviewer decisions above.</p><div className="summary-decisions">{Object.entries(technical).map(([status, count]) => <span key={status}>{label(status)} <b>{count}</b></span>)}</div>{!report.technicalFindings.length && <p>No technical findings for this run.</p>}</section>
      <p className="summary-updated">Generated {new Date(report.generatedAt).toLocaleString()}. Refresh to include reviews saved in another session.</p>
    </>}
  </section>;
}

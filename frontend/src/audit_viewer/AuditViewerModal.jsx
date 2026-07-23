import { useEffect, useMemo, useRef, useState } from 'react';
import ReactDOM from 'react-dom';
import { fetchAuditGraph } from './api';
import AuditGraph from './AuditGraph';
import AuditTimeline from './AuditTimeline';
import AuditSidePanel from './AuditSidePanel';
import './AuditViewer.css';

const ROLE_ORDER = ['root', 'supplier', 'parent', 'legacy', 'unknown'];

const AuditViewerModal = ({ runId, companyName, onClose }) => {
  const [data, setData] = useState(null); const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(null); const [view, setView] = useState('graph');
  const [entity, setEntity] = useState(null); const [type, setType] = useState('all'); const [query, setQuery] = useState('');
  const [collapseTrigger, setCollapseTrigger] = useState(0);
  const closeRef = useRef(null);

  useEffect(() => { closeRef.current?.focus(); const onKey = (event) => event.key === 'Escape' && onClose(); window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey); }, [onClose]);
  useEffect(() => { fetchAuditGraph(runId, companyName).then(setData).catch((err) => setError(err.message)); }, [runId, companyName]);

  // Provenance-first: the entity switcher defaults to the root company (entity === null
  // means "auto"); the user's explicit choice takes over once made.
  const rootEntity = useMemo(() => data?.entities.find((scope) => scope.role === 'root')?.name || 'all', [data]);
  const activeEntity = entity ?? rootEntity;

  const events = useMemo(() => (data?.events || []).filter((event) =>
    (activeEntity === 'all' || event.entity_name === activeEntity) && (type === 'all' || event.event_type === type) &&
    JSON.stringify(event).toLowerCase().includes(query.toLowerCase())), [data, activeEntity, type, query]);

  const entityGroups = useMemo(() => {
    const byRole = new Map();
    for (const scope of (data?.entities || [])) {
      if (!byRole.has(scope.role)) byRole.set(scope.role, []);
      byRole.get(scope.role).push(scope);
    }
    return [...byRole.entries()].sort((a, b) => ROLE_ORDER.indexOf(a[0]) - ROLE_ORDER.indexOf(b[0]));
  }, [data]);
  const eventTypes = useMemo(() => [...new Set((data?.events || []).map((e) => e.event_type))].sort(), [data]);

  const selected = events.find((event) => event.event_id === selectedId) || null;
  const summary = data?.summary;

  return ReactDOM.createPortal(<div className="audit-modal-overlay" role="presentation"><section className="audit-modal-content" role="dialog" aria-modal="true" aria-label={`Audit trail for ${companyName}`}>
    <header className="audit-modal-header"><div><h2>Audit Trail: {companyName}</h2>{summary && <p>{summary.status} · {summary.agents_completed} completed · {summary.agents_failed} failed · {summary.high_risk_flags} priority flags</p>}</div><button ref={closeRef} className="close-button" onClick={onClose}>Close</button></header>
    {error && <p className="audit-error">{error}</p>}{!data && !error && <p className="audit-loading">Loading audit trail…</p>}
    {data && <><div className="audit-metrics"><span>{summary.total_events} events</span><span>{summary.retrievals} retrievals</span><span>{summary.generations} generations</span><span>{summary.evidence_events} evidence sets</span></div>
      <div className="audit-toolbar">
        <select value={activeEntity} onChange={(e) => setEntity(e.target.value)} aria-label="Filter entity">
          <option value="all">All entities</option>
          {entityGroups.map(([role, scopes]) => <optgroup key={role} label={role}>{scopes.map((scope) => <option key={`${scope.name}-${scope.role}`} value={scope.name}>{scope.name} ({scope.event_count})</option>)}</optgroup>)}
        </select>
        <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Filter event type">
          <option value="all">All events</option>
          {eventTypes.map((item) => <option key={item} value={item}>{item.replaceAll('_', ' ')}</option>)}
        </select>
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search audit events" aria-label="Search audit events" />
        <button onClick={() => setView('graph')} aria-pressed={view === 'graph'}>Causal graph</button>
        <button onClick={() => setView('timeline')} aria-pressed={view === 'timeline'}>Timeline</button>
        {view === 'graph' && <button onClick={() => setCollapseTrigger((t) => t + 1)}>Collapse All</button>}
      </div>
      <main className="audit-modal-body"><div className="audit-graph-container">
        {view === 'graph'
          ? <AuditGraph events={events} dagDependencies={data.dag_dependencies} selectedId={selectedId} onNodeClick={setSelectedId} collapseTrigger={collapseTrigger} />
          : <AuditTimeline events={events} selectedId={selectedId} onSelect={setSelectedId} />}
      </div><AuditSidePanel event={selected} /></main>
    </>}</section></div>, document.body);
};
export default AuditViewerModal;

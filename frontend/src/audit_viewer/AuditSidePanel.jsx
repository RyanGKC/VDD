import { useState, useEffect } from 'react';
import { fetchRawChunks } from './api';

const AuditSidePanel = ({ event, reviewView = false, reviews = [], contradictions = [] }) => {
  const [evidence, setEvidence] = useState(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEvidence(null);
  }, [event?.event_id]);

  if (reviewView) {
    return <aside className="audit-side-panel" aria-live="polite">
      <p className="audit-event-type">Supervisor · batch quality control</p>
      <h3>Review timeline</h3>
      {reviews.length === 0 && <p>No supervisor review rounds recorded for this run.</p>}
      {reviews.map((r) => <div key={r.eventId || r.round} className={`audit-sup-round ${r.isAnomaly ? 'anomaly' : 'clear'}`}>
        <div className="audit-sup-round__head">
          <span className={`audit-sup-pill ${r.isAnomaly ? 'rej' : 'acc'}`}>{r.isAnomaly ? '⚠ Anomaly' : '✓ Clear'}</span>
          <span className="audit-sup-round__n">Round {r.round}</span>
        </div>
        <p>{r.rationale}</p>
        {r.steps.length > 0 && <div className="audit-sup-steps">Re-ran: {r.steps.join(', ')}</div>}
        {Object.keys(r.updatedParams || {}).length > 0 && <div className="audit-sup-steps">Updated: {Object.entries(r.updatedParams).map(([k, v]) => `${k}=${v}`).join(', ')}</div>}
      </div>)}
      {contradictions.length > 0 && <section className="audit-sup-contra">
        <h4>Contradiction check</h4>
        {contradictions.map((c, i) => <p key={i}>Removed: {c}</p>)}
      </section>}
    </aside>;
  }

  if (!event) return <aside className="audit-side-panel"><p>Select an event to inspect its provenance.</p></aside>;
  const loadEvidence = async () => {
    setLoading(true);
    try { setEvidence(await fetchRawChunks(event.event_id)); } catch { setEvidence({ available: false, chunks: [] }); }
    setLoading(false);
  };
  return <aside className="audit-side-panel" aria-live="polite">
    <p className="audit-event-type">{event.event_type.replaceAll('_', ' ')}</p>
    <h3>{event.agent_id.replaceAll('_', ' ')}</h3>
    <p className="audit-event-time">{new Date(event.timestamp).toLocaleString()} · {event.status || 'recorded'}</p>
    <dl className="audit-details">
      <dt>Entity</dt><dd>{event.entity_name || 'Unknown'} ({event.entity_role || 'legacy'})</dd>
      {event.model_version && <><dt>Model</dt><dd>{event.model_version}</dd></>}
      {Object.entries(event.payload || {}).filter(([key]) => !['chunk_ids', 'supporting_chunk_ids'].includes(key)).map(([key, value]) =>
        <><dt key={`${key}-term`}>{key.replaceAll('_', ' ')}</dt><dd key={`${key}-value`}>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></>)}
    </dl>
    {event.event_type === 'retrieval' && !evidence && <button className="fetch-raw-btn" onClick={loadEvidence} disabled={loading}>{loading ? 'Loading evidence…' : 'View retained evidence'}</button>}
    {evidence && <>
      <button className="fetch-raw-btn" onClick={() => setEvidence(null)} style={{ marginTop: '0.5rem', background: '#64748b' }}>Hide evidence</button>
      <section className="raw-chunk-display">
      {!evidence.available ? <p>Evidence is unavailable for this legacy or non-retained event.</p> : evidence.chunks.map((chunk) => <article key={chunk.id}><small>{chunk.metadata.source_domains?.join(', ') || chunk.metadata.source || 'Recorded source'}</small><p>{chunk.text}</p></article>)}
      </section>
    </>}
  </aside>;
};
export default AuditSidePanel;

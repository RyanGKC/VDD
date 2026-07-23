import { useEffect, useMemo, useRef } from 'react';
import {
  EVENT_COLORS, STATUS_COLORS, groupByAgent, agentStatus, agentDuration,
  agentCounts, countsLabel, payloadPreview,
} from './auditModel';

// Timeline view: events grouped by agent, each group ordered chronologically and
// annotated with its real duration/status. Shares `selectedId` with the graph so
// selecting in either view keeps the side panel and highlight in sync.
const AuditTimeline = ({ events, selectedId, onSelect }) => {
  const groups = useMemo(() => {
    const { groups: byAgent } = groupByAgent(events);
    return [...byAgent.entries()]
      .filter(([agent]) => agent !== 'system' || byAgent.size === 1)
      .map(([agent, agentEvents]) => ({
        agent,
        events: [...agentEvents].sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp)),
      }))
      .sort((a, b) => Date.parse(a.events[0].timestamp) - Date.parse(b.events[0].timestamp));
  }, [events]);

  const selectedRef = useRef(null);
  useEffect(() => {
    selectedRef.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
  }, [selectedId]);

  return (
    <div className="audit-timeline-container">
      {groups.map(({ agent, events: agentEvents }) => {
        const counts = agentCounts(agentEvents);
        const duration = agentDuration(agentEvents);
        const status = agentStatus(agentEvents);
        return (
          <section className="audit-tl-group" key={agent}>
            <header className="audit-tl-group__header">
              <span className="audit-tl-group__title" style={{ '--status-color': STATUS_COLORS[status] || '#3b82f6' }}>
                {agent.replaceAll('_', ' ')}
              </span>
              <span className="audit-tl-group__meta">
                {countsLabel(counts)}{duration ? ` · ${duration}` : ''}
              </span>
            </header>
            <ol className="audit-tl-events">
              {agentEvents.map((event) => {
                const selected = event.event_id === selectedId;
                return (
                  <li key={event.event_id} ref={selected ? selectedRef : null}>
                    <button
                      className={`audit-tl-row${selected ? ' audit-tl-row--selected' : ''}`}
                      onClick={() => onSelect(event.event_id)}
                    >
                      <span className="audit-tl-row__dot" style={{ background: EVENT_COLORS[event.event_type] || '#475569' }} />
                      <span className="audit-tl-row__body">
                        <span className="audit-tl-row__head">
                          <strong>{event.event_type.replaceAll('_', ' ')}</strong>
                          <time>{new Date(event.timestamp).toLocaleTimeString()}</time>
                        </span>
                        <span className="audit-tl-row__preview">{payloadPreview(event)}</span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </section>
        );
      })}
    </div>
  );
};

export default AuditTimeline;

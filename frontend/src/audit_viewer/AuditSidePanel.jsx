import React, { useState } from 'react';
import { fetchRawChunks } from './api';

const AuditSidePanel = ({ node, events }) => {
  const [rawChunks, setRawChunks] = useState({});
  const [loadingChunks, setLoadingChunks] = useState({});

  if (!node) {
    return (
      <div className="audit-side-panel">
        <p>Select a node to view audit events.</p>
      </div>
    );
  }

  const handleFetchChunks = async (eventId, chunkIds) => {
    setLoadingChunks((prev) => ({ ...prev, [eventId]: true }));
    try {
      const data = await fetchRawChunks(chunkIds);
      setRawChunks((prev) => ({ ...prev, [eventId]: data.chunks }));
    } catch (error) {
      setRawChunks((prev) => ({
        ...prev,
        [eventId]: [{ id: 'error', text: 'Raw text no longer available (Retention period expired or cleared)' }],
      }));
    } finally {
      setLoadingChunks((prev) => ({ ...prev, [eventId]: false }));
    }
  };

  return (
    <div className="audit-side-panel">
      <h3>{node.data.label} ({events.length} Events)</h3>
      {events.map((event) => (
        <div key={event.event_id} className="audit-event-card">
          <div className="audit-event-type">{event.event_type}</div>
          <div className="audit-event-time">{new Date(event.timestamp).toLocaleString()}</div>
          
          {Object.entries(event.payload).map(([key, value]) => {
            if (key === 'chunk_ids' || key === 'relevance_scores') return null; // Handle separately
            
            let displayValue = value;
            if (Array.isArray(value)) displayValue = value.join(', ');
            else if (typeof value === 'object') displayValue = JSON.stringify(value);

            return (
              <div key={key} className="audit-event-payload">
                <strong>{key}:</strong> {displayValue}
              </div>
            );
          })}

          {event.payload.chunk_ids && event.payload.chunk_ids.length > 0 && (
            <div style={{ marginTop: '10px' }}>
              <button 
                className="fetch-raw-btn"
                onClick={() => handleFetchChunks(event.event_id, event.payload.chunk_ids)}
                disabled={loadingChunks[event.event_id]}
              >
                {loadingChunks[event.event_id] ? 'Fetching...' : 'View Raw Text'}
              </button>

              {rawChunks[event.event_id] && (
                <div className="raw-chunk-display">
                  {rawChunks[event.event_id].length === 0 ? (
                    <span>Raw text no longer available (Retention period expired or cleared)</span>
                  ) : (
                    rawChunks[event.event_id].map((c, idx) => (
                      <div key={idx} style={{ marginBottom: '10px', borderBottom: '1px solid #333', paddingBottom: '10px' }}>
                        <div><strong>ID:</strong> {c.id}</div>
                        <div>{c.text}</div>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
};

export default AuditSidePanel;

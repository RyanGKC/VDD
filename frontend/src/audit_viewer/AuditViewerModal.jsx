import React, { useEffect, useState } from 'react';
import ReactDOM from 'react-dom';
import { fetchAuditGraph } from './api';
import AuditGraph from './AuditGraph';
import AuditSidePanel from './AuditSidePanel';
import './AuditViewer.css';

const AuditViewerModal = ({ runId, companyName, onClose }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);

  useEffect(() => {
    const loadGraph = async () => {
      try {
        setLoading(true);
        const res = await fetchAuditGraph(runId, companyName);
        setData(res);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };
    if (runId && companyName) {
      loadGraph();
    }
  }, [runId, companyName]);

  const handleNodeClick = (node) => {
    setSelectedNode(node);
  };

  const modalContent = (
    <div className="audit-modal-overlay">
      <div className="audit-modal-content">
        <div className="audit-modal-header">
          <h2>Audit Trail: {companyName}</h2>
          <button className="close-button" onClick={onClose}>Close</button>
        </div>
        
        <div className="audit-modal-body">
          {loading && <div style={{ padding: '2rem', color: '#fff' }}>Loading Audit Graph...</div>}
          {error && <div style={{ padding: '2rem', color: '#ff4b4b' }}>Error: {error}</div>}
          
          {!loading && !error && data && (
            <>
              <div className="audit-graph-container">
                <AuditGraph data={data} onNodeClick={handleNodeClick} />
              </div>
              <AuditSidePanel 
                node={selectedNode} 
                events={selectedNode ? (data.event_groups[selectedNode.id] || []) : []} 
              />
            </>
          )}
        </div>
      </div>
    </div>
  );

  return ReactDOM.createPortal(modalContent, document.body);
};

export default AuditViewerModal;

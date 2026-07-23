import { useCallback, useEffect, useMemo, useState } from 'react';
import ReactFlow, { Background, Controls, MiniMap, MarkerType } from 'reactflow';
import dagre from 'dagre';
import 'reactflow/dist/style.css';
import {
  EVENT_COLORS, STATUS_COLORS, groupByAgent, ancestorChain, transitiveDeps,
  resolveAgent, agentDuration, countsLabel,
} from './auditModel';
import { buildGraphModel } from './auditGraphModel';

// ─── Sub-graph layout (an agent's internal causal trace) ─────────────────────

function layoutAgentSubgraph(agentEvents) {
  const subG = new dagre.graphlib.Graph();
  subG.setDefaultEdgeLabel(() => ({}));
  subG.setGraph({ rankdir: 'LR', ranksep: 60, nodesep: 20, marginx: 12, marginy: 40 });

  for (const event of agentEvents) subG.setNode(event.event_id, { width: 170, height: 46 });

  const ids = new Set(agentEvents.map((e) => e.event_id));
  for (const event of agentEvents) {
    if (event.parent_event_id && ids.has(event.parent_event_id)) {
      subG.setEdge(event.parent_event_id, event.event_id);
    }
  }
  dagre.layout(subG);

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const event of agentEvents) {
    const pos = subG.node(event.event_id);
    if (!pos) continue;
    minX = Math.min(minX, pos.x - pos.width / 2);
    minY = Math.min(minY, pos.y - pos.height / 2);
    maxX = Math.max(maxX, pos.x + pos.width / 2);
    maxY = Math.max(maxY, pos.y + pos.height / 2);
  }
  if (!Number.isFinite(minX)) { minX = minY = 0; maxX = 180; maxY = 46; }

  const headerHeight = 34, padX = 16, padY = 12;
  const groupWidth = (maxX - minX) + padX * 2;
  const groupHeight = (maxY - minY) + padY * 2 + headerHeight;

  const childPositions = new Map();
  for (const event of agentEvents) {
    const pos = subG.node(event.event_id);
    if (!pos) continue;
    childPositions.set(event.event_id, {
      x: (pos.x - pos.width / 2) - minX + padX,
      y: (pos.y - pos.height / 2) - minY + padY + headerHeight,
    });
  }
  return { groupWidth, groupHeight, childPositions };
}

// ─── Custom node components ──────────────────────────────────────────────────

function nodeClass(base, { dimmed, selected, focused }) {
  return [base, dimmed && 'audit-node--dim', selected && 'audit-node--selected', focused && 'audit-node--focus']
    .filter(Boolean).join(' ');
}

function CollapsedAgentNode({ data }) {
  const border = STATUS_COLORS[data.status] || '#3b82f6';
  return (
    <div className={nodeClass('audit-node-agent', data)} style={{ borderColor: border }}>
      <div className="audit-node-agent__title">
        {data.agentId.replaceAll('_', ' ')}
        {data.highFlags > 0 && <span className="audit-node-agent__badge">{data.highFlags}</span>}
      </div>
      <div className="audit-node-agent__meta">{data.summary}</div>
      <div className="audit-node-agent__foot">
        {data.duration && <span>{data.duration}</span>}
        {data.attemptCount > 1 && <span className="audit-node-agent__rerun">⟲ {data.attemptCount - 1} re-run</span>}
        <span className="audit-node-agent__hint">▸ expand</span>
      </div>
    </div>
  );
}

function ExpandedEventNode({ data }) {
  const color = EVENT_COLORS[data.event.event_type] || '#475569';
  return (
    <div className={nodeClass('audit-node-event', data)} style={{ background: color }}>
      <strong>{data.event.event_type.replaceAll('_', ' ')}</strong>
      <div className="audit-node-event__sub">{data.event.agent_id.replaceAll('_', ' ')}</div>
    </div>
  );
}

function PipelineNode({ data }) {
  const isStart = data.kind === 'start';
  return (
    <div className={nodeClass(`audit-node-pipeline ${isStart ? '' : 'audit-node-pipeline--end'}`, data)}>
      {isStart ? '▶ Pipeline Start' : '■ Report compiled'}
    </div>
  );
}

function ReviewLaneNode({ data }) {
  return (
    <div className={nodeClass('audit-node-review', data)}>
      <div className="audit-node-review__title">⚖ Supervisor</div>
      <div className="audit-node-review__meta">
        {data.rounds} round{data.rounds === 1 ? '' : 's'}
        {data.anomalies > 0 && <span className="audit-node-review__flag"> · {data.anomalies} anomaly</span>}
      </div>
      <div className="audit-node-agent__hint">▸ review timeline</div>
    </div>
  );
}

function AgentGroupNode({ data }) {
  return (
    <div className={nodeClass('audit-group', data)}>
      <div className="audit-group__header">
        <span className="audit-group__title">{data.agentId.replaceAll('_', ' ')}</span>
        <button className="audit-group__close" onClick={(e) => { e.stopPropagation(); data.onCollapse(data.agentId); }}>✕</button>
      </div>
    </div>
  );
}

const nodeTypes = {
  collapsed: CollapsedAgentNode, expanded: ExpandedEventNode, pipeline: PipelineNode,
  review: ReviewLaneNode, group: AgentGroupNode,
};

// Edge styling per model edge kind.
const EDGE_STYLE = {
  start: { stroke: '#3b82f6', arrow: '#3b82f6' },
  dep: { stroke: '#3b82f6', arrow: '#3b82f6' },
  bus: { stroke: '#3b82f6', arrow: '#3b82f6' },
  reviewToSummary: { stroke: '#22c55e', arrow: '#22c55e' },
  summaryToEnd: { stroke: '#22c55e', arrow: '#22c55e' },
};

// ─── Main component ──────────────────────────────────────────────────────────

const AuditGraph = ({ events, dagDependencies, selectedId, onNodeClick, collapseTrigger, reviews = [] }) => {
  const [expandedAgents, setExpandedAgents] = useState(new Set());

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setExpandedAgents(new Set());
  }, [collapseTrigger]);

  const toggleAgent = useCallback((agentId) => {
    setExpandedAgents((prev) => {
      const next = new Set(prev);
      if (next.has(agentId)) next.delete(agentId); else next.add(agentId);
      return next;
    });
  }, []);

  const { nodes, flowEdges } = useMemo(() => {
    const dag = dagDependencies || {};
    const model = buildGraphModel(events, dag, reviews);
    const { maps } = groupByAgent(events);

    // Focus/trace: light up the selected event's causal ancestry + prerequisite agents.
    const selectedEvent = selectedId && selectedId !== '__review__' ? events.find((e) => e.event_id === selectedId) : null;
    const hasFocus = Boolean(selectedEvent);
    const selectedAgent = selectedEvent ? resolveAgent(selectedEvent.agent_id, selectedEvent.event_id, maps) : null;
    const ancestors = selectedEvent ? ancestorChain(selectedId, maps) : new Set();
    const focusAgents = selectedAgent ? new Set([selectedAgent, ...transitiveDeps(selectedAgent, dag)]) : new Set();

    const startEvent = events.find((e) => e.event_type === 'pipeline_start');
    const endEvents = events.filter((e) => e.event_type === 'pipeline_end');
    const endEvent = endEvents[endEvents.length - 1];
    const hasReview = model.columns.some((c) => c.kind === 'review');

    // Map a model token to a React Flow node id (undefined when its node is absent).
    const rfId = (token) => {
      if (token === '__start__') return startEvent?.event_id;
      if (token === '__report__') return endEvent?.event_id;
      if (token === '__review__') return hasReview ? 'review' : undefined;
      return `agent-${token}`;
    };

    const g = new dagre.graphlib.Graph();
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({ rankdir: 'LR', ranksep: 130, nodesep: 40, marginx: 30, marginy: 30 });

    const resultNodes = [];
    const resultEdges = [];
    const nodeIds = new Set();
    const addNode = (node, dimmed, opts = {}) => {
      nodeIds.add(node.id);
      resultNodes.push({
        ...node, data: { ...node.data, dimmed, ...opts },
        style: { ...(node.style || {}), opacity: dimmed ? 0.28 : 1 },
      });
    };

    if (startEvent) {
      g.setNode(startEvent.event_id, { width: 160, height: 50 });
      addNode({ id: startEvent.event_id, type: 'pipeline', position: { x: 0, y: 0 }, data: { kind: 'start' } }, false);
    }
    if (endEvent) {
      g.setNode(endEvent.event_id, { width: 160, height: 50 });
      addNode({ id: endEvent.event_id, type: 'pipeline', position: { x: 0, y: 0 }, data: { kind: 'end' } }, false);
    }
    if (hasReview) {
      g.setNode('review', { width: 210, height: 96 });
      const anomalies = reviews.filter((r) => r.isAnomaly).length;
      addNode({ id: 'review', type: 'review', position: { x: 0, y: 0 }, data: { rounds: reviews.length, anomalies } },
        false, { selected: selectedId === '__review__' });
    }

    for (const agent of model.agents) {
      const finalEvents = agent.attempts[agent.attempts.length - 1]?.events || [];
      const isExpanded = expandedAgents.has(agent.id);
      const focused = !hasFocus || focusAgents.has(agent.id);
      const dimmed = hasFocus && !focused;
      const agentNodeId = `agent-${agent.id}`;
      const { groupWidth, groupHeight, childPositions } = layoutAgentSubgraph(finalEvents);
      g.setNode(agentNodeId, { width: groupWidth, height: groupHeight });

      if (isExpanded) {
        addNode({
          id: agentNodeId, type: 'group', position: { x: 0, y: 0 },
          data: { agentId: agent.id, onCollapse: toggleAgent }, style: { width: groupWidth, height: groupHeight },
        }, dimmed, { focused, selected: agent.id === selectedAgent });

        for (const event of finalEvents) {
          const pos = childPositions.get(event.event_id);
          if (!pos) continue;
          const onPath = ancestors.has(event.event_id);
          resultNodes.push({
            id: event.event_id, type: 'expanded', position: { x: pos.x, y: pos.y },
            parentNode: agentNodeId, extent: 'parent',
            data: { event, dimmed: hasFocus && !onPath, focused: hasFocus && onPath, selected: event.event_id === selectedId },
            style: { opacity: hasFocus && !onPath ? 0.28 : 1 },
          });
        }

        const ids = new Set(finalEvents.map((e) => e.event_id));
        for (const event of finalEvents) {
          if (event.parent_event_id && ids.has(event.parent_event_id)) {
            const onPath = ancestors.has(event.event_id) && ancestors.has(event.parent_event_id);
            resultEdges.push({
              id: `edge-${event.event_id}`, source: event.parent_event_id, target: event.event_id,
              animated: true, style: { stroke: onPath ? '#f8fafc' : '#64748b', opacity: hasFocus && !onPath ? 0.15 : 1 },
            });
          }
        }
      } else {
        const representative = finalEvents.find((e) => e.event_type === 'dag_node_start') || finalEvents[0];
        addNode({
          id: agentNodeId, type: 'collapsed', position: { x: 0, y: 0 },
          data: {
            agentId: agent.id, summary: countsLabel(agent.counts), highFlags: agent.counts.highFlags,
            status: agent.status, duration: agentDuration(finalEvents), attemptCount: agent.attempts.length,
            representativeId: representative?.event_id,
          },
        }, dimmed, { focused, selected: agent.id === selectedAgent });
      }
    }

    // Inter-node edges from the model, mapped to real node ids (skip missing endpoints; feedback handled below).
    for (const edge of model.edges) {
      if (edge.kind === 'feedback') continue;
      const source = rfId(edge.from);
      const target = rfId(edge.to);
      if (!source || !target || !nodeIds.has(source) || !nodeIds.has(target)) continue;
      g.setEdge(source, target);
      const involves = !hasFocus || [edge.from, edge.to].some((t) => focusAgents.has(t));
      const s = EDGE_STYLE[edge.kind] || EDGE_STYLE.dep;
      resultEdges.push({
        id: `dep-${edge.kind}-${edge.from}-${edge.to}`, source, target, animated: true,
        style: { stroke: s.stroke, strokeWidth: 2, opacity: involves ? 1 : 0.15 },
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: s.arrow },
      });
    }

    dagre.layout(g);
    for (const node of resultNodes) {
      if (node.parentNode) continue;
      const pos = g.node(node.id);
      if (pos) node.position = { x: pos.x - (pos.width || 0) / 2, y: pos.y - (pos.height || 0) / 2 };
    }

    // Feedback edges (review → re-run agents) are visual-only, added after layout so they never
    // create dagre cycles. Dashed amber, drawn on top.
    for (const edge of model.edges) {
      if (edge.kind !== 'feedback') continue;
      const source = rfId(edge.from);
      const target = rfId(edge.to);
      if (!source || !target || !nodeIds.has(source) || !nodeIds.has(target)) continue;
      resultEdges.push({
        id: `feedback-${edge.to}`, source, target, animated: false,
        style: { stroke: '#e0a458', strokeWidth: 1.5, strokeDasharray: '5 4', opacity: 0.85 },
        markerEnd: { type: MarkerType.ArrowClosed, width: 11, height: 11, color: '#e0a458' },
      });
    }

    return { nodes: resultNodes, flowEdges: resultEdges };
  }, [events, dagDependencies, reviews, selectedId, expandedAgents, toggleAgent]);

  const handleNodeClick = useCallback((_, node) => {
    if (node.type === 'collapsed') {
      toggleAgent(node.data.agentId);
      if (node.data.representativeId) onNodeClick(node.data.representativeId);
    } else if (node.type === 'group') {
      onNodeClick(node.data.agentId);
    } else if (node.type === 'review') {
      onNodeClick('__review__');
    } else if (node.type === 'expanded') {
      onNodeClick(node.data.event.event_id);
    }
  }, [onNodeClick, toggleAgent]);

  return (
    <ReactFlow
      nodes={nodes} edges={flowEdges} nodeTypes={nodeTypes} onNodeClick={handleNodeClick}
      fitView fitViewOptions={{ padding: 0.15 }} minZoom={0.1} maxZoom={2}
    >
      <Background color="#475569" gap={24} />
      <Controls />
      <MiniMap
        nodeColor={(n) => (n.type === 'collapsed' || n.type === 'group' || n.type === 'review') ? '#1e293b' : (EVENT_COLORS[n.data?.event?.event_type] || '#475569')}
        style={{ background: '#0f172a' }}
      />
      <div className="audit-graph-legend">
        <span style={{ '--dot-color': '#2563eb' }}>Agent</span>
        <span style={{ '--dot-color': '#4f46e5' }}>Retrieval</span>
        <span style={{ '--dot-color': '#7c3aed' }}>Generation</span>
        <span style={{ '--dot-color': '#dc2626' }}>Risk Flag</span>
        <span style={{ '--dot-color': '#e0a458' }}>Re-run</span>
      </div>
    </ReactFlow>
  );
};

export default AuditGraph;

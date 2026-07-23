import { useCallback, useEffect, useMemo, useState } from 'react';
import ReactFlow, { Background, Controls, MiniMap, MarkerType } from 'reactflow';
import dagre from 'dagre';
import 'reactflow/dist/style.css';
import {
  EVENT_COLORS, STATUS_COLORS, groupByAgent, ancestorChain, transitiveDeps,
  resolveAgent, agentCounts, agentStatus, agentDuration, countsLabel,
} from './auditModel';

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
  const isStart = data.event.event_type === 'pipeline_start';
  return (
    <div className={nodeClass(`audit-node-pipeline ${isStart ? '' : 'audit-node-pipeline--end'}`, data)}>
      {isStart ? '▶ Pipeline Start' : '■ Pipeline End'}
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

const nodeTypes = { collapsed: CollapsedAgentNode, expanded: ExpandedEventNode, pipeline: PipelineNode, group: AgentGroupNode };

const DEP_EDGE = (id, source, target, focused) => ({
  id, source, target, animated: true,
  style: { stroke: '#3b82f6', strokeWidth: 2, opacity: focused ? 1 : 0.15 },
  markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: '#3b82f6' },
});

// ─── Main component ──────────────────────────────────────────────────────────

const AuditGraph = ({ events, dagDependencies, selectedId, onNodeClick, collapseTrigger }) => {
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
    const { groups, maps } = groupByAgent(events);

    // Focus/trace: light up the selected event's causal ancestry and the
    // dependency chain of prerequisites that fed the agent it belongs to.
    const selectedEvent = selectedId ? events.find((e) => e.event_id === selectedId) : null;
    const hasFocus = Boolean(selectedEvent);
    const selectedAgent = selectedEvent ? resolveAgent(selectedEvent.agent_id, selectedEvent.event_id, maps) : null;
    const ancestors = selectedEvent ? ancestorChain(selectedId, maps) : new Set();
    const focusAgents = selectedAgent ? new Set([selectedAgent, ...transitiveDeps(selectedAgent, dag)]) : new Set();
    const agentFocused = (agent) => !hasFocus || focusAgents.has(agent);

    const startEvent = events.find((e) => e.event_type === 'pipeline_start');
    const endEvents = events.filter((e) => e.event_type === 'pipeline_end');
    const endEvent = endEvents[endEvents.length - 1];

    const stepAgents = [...groups.keys()].filter((key) => key in dag);
    const present = new Set(stepAgents);
    const dependedOn = new Set();
    for (const step of stepAgents) for (const dep of (dag[step] || [])) if (present.has(dep)) dependedOn.add(dep);
    const terminals = stepAgents.filter((step) => !dependedOn.has(step));

    const g = new dagre.graphlib.Graph();
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({ rankdir: 'LR', ranksep: 140, nodesep: 40, marginx: 30, marginy: 30 });

    const resultNodes = [];
    const resultEdges = [];
    const addNode = (node, dimmed, opts = {}) => resultNodes.push({
      ...node, data: { ...node.data, dimmed, ...opts },
      style: { ...(node.style || {}), opacity: dimmed ? 0.28 : 1 },
    });

    if (startEvent) {
      g.setNode(startEvent.event_id, { width: 160, height: 50 });
      addNode({ id: startEvent.event_id, type: 'pipeline', position: { x: 0, y: 0 }, data: { event: startEvent } }, false);
    }

    for (const [agentId, agentEvents] of groups) {
      if (agentId === 'system') continue;

      const isExpanded = expandedAgents.has(agentId);
      const focused = agentFocused(agentId);
      const dimmed = hasFocus && !focused;
      const agentNodeId = `agent-${agentId}`;
      const { groupWidth, groupHeight, childPositions } = layoutAgentSubgraph(agentEvents);
      g.setNode(agentNodeId, { width: groupWidth, height: groupHeight });

      if (isExpanded) {
        addNode({
          id: agentNodeId, type: 'group', position: { x: 0, y: 0 },
          data: { agentId, onCollapse: toggleAgent }, style: { width: groupWidth, height: groupHeight },
        }, dimmed, { focused, selected: agentId === selectedAgent && !selectedEvent?.event_id });

        for (const event of agentEvents) {
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

        const ids = new Set(agentEvents.map((e) => e.event_id));
        for (const event of agentEvents) {
          if (event.parent_event_id && ids.has(event.parent_event_id)) {
            const onPath = ancestors.has(event.event_id) && ancestors.has(event.parent_event_id);
            resultEdges.push({
              id: `edge-${event.event_id}`, source: event.parent_event_id, target: event.event_id,
              animated: true, style: { stroke: onPath ? '#f8fafc' : '#64748b', opacity: hasFocus && !onPath ? 0.15 : 1 },
            });
          }
        }
      } else {
        const counts = agentCounts(agentEvents);
        const representative = agentEvents.find((e) => e.event_type === 'dag_node_start') || agentEvents[0];
        addNode({
          id: agentNodeId, type: 'collapsed', position: { x: 0, y: 0 },
          data: {
            agentId, summary: countsLabel(counts), highFlags: counts.highFlags,
            status: agentStatus(agentEvents), duration: agentDuration(agentEvents),
            representativeId: representative?.event_id,
          },
        }, dimmed, { focused, selected: agentId === selectedAgent });
      }

      // Inter-agent dependency edges, sourced from the real dependency DAG.
      const deps = (dag[agentId] || []).filter((d) => present.has(d));
      if (deps.length === 0 && startEvent) {
        g.setEdge(startEvent.event_id, agentNodeId);
        resultEdges.push(DEP_EDGE(`dep-start-${agentId}`, startEvent.event_id, agentNodeId, agentFocused(agentId)));
      }
      for (const dep of deps) {
        g.setEdge(`agent-${dep}`, agentNodeId);
        resultEdges.push(DEP_EDGE(`dep-${dep}-${agentId}`, `agent-${dep}`, agentNodeId, focused && agentFocused(dep)));
      }
    }

    // Terminal steps fan into the summary agent (or the pipeline end).
    const hasSummary = groups.has('summary_agent');
    const summaryNodeId = 'agent-summary_agent';
    for (const terminal of terminals) {
      const target = hasSummary ? summaryNodeId : (endEvent ? endEvent.event_id : null);
      if (!target) continue;
      g.setEdge(`agent-${terminal}`, target);
      const focused = agentFocused(terminal);
      resultEdges.push({
        id: `dep-${terminal}-terminal`, source: `agent-${terminal}`, target, animated: true,
        style: { stroke: '#22c55e', strokeWidth: 2, opacity: focused ? 1 : 0.15 },
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: '#22c55e' },
      });
    }

    if (endEvent && hasSummary) {
      g.setNode(endEvent.event_id, { width: 160, height: 50 });
      addNode({ id: endEvent.event_id, type: 'pipeline', position: { x: 0, y: 0 }, data: { event: endEvent } }, false);
      g.setEdge(summaryNodeId, endEvent.event_id);
      resultEdges.push({
        id: 'dep-summary-end', source: summaryNodeId, target: endEvent.event_id, animated: true,
        style: { stroke: '#22c55e', strokeWidth: 2 },
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: '#22c55e' },
      });
    }

    dagre.layout(g);
    for (const node of resultNodes) {
      if (node.parentNode) continue;
      const pos = g.node(node.id);
      if (pos) node.position = { x: pos.x - (pos.width || 0) / 2, y: pos.y - (pos.height || 0) / 2 };
    }

    return { nodes: resultNodes, flowEdges: resultEdges };
  }, [events, dagDependencies, selectedId, expandedAgents, toggleAgent]);

  const handleNodeClick = useCallback((_, node) => {
    if (node.type === 'collapsed') {
      toggleAgent(node.data.agentId);
      if (node.data.representativeId) onNodeClick(node.data.representativeId);
    } else if (node.type === 'expanded' || node.type === 'pipeline') {
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
        nodeColor={(n) => n.type === 'collapsed' || n.type === 'group' ? '#1e293b' : (EVENT_COLORS[n.data?.event?.event_type] || '#475569')}
        style={{ background: '#0f172a' }}
      />
      <div className="audit-graph-legend">
        <span style={{ '--dot-color': '#2563eb' }}>Agent</span>
        <span style={{ '--dot-color': '#4f46e5' }}>Retrieval</span>
        <span style={{ '--dot-color': '#7c3aed' }}>Generation</span>
        <span style={{ '--dot-color': '#dc2626' }}>Risk Flag</span>
        <span style={{ '--dot-color': '#334155' }}>Pipeline</span>
      </div>
    </ReactFlow>
  );
};

export default AuditGraph;

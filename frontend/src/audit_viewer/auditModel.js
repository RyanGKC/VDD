// Shared audit-trail model helpers used by both the causal graph and the timeline.
// Keeps agent grouping, causal-chain walking, and per-agent stats in one place so
// the graph and timeline always agree on how events roll up into agents.

export const EVENT_COLORS = {
  pipeline_start: '#334155', pipeline_end: '#334155',
  dag_node_start: '#2563eb', dag_node_end: '#2563eb',
  retrieval: '#4f46e5', generation: '#7c3aed',
  risk_flag: '#dc2626', tool_call: '#059669',
};

export const STATUS_COLORS = {
  completed: '#22c55e', failed: '#ef4444', running: '#eab308', flagged: '#f59e0b',
};

// Maps used to walk the causal tree: event -> parent event, and event -> raw agent.
export function buildParentMap(events) {
  const parentOf = new Map();
  const agentOf = new Map();
  for (const event of events) {
    if (event.parent_event_id) parentOf.set(event.event_id, event.parent_event_id);
    agentOf.set(event.event_id, event.agent_id);
  }
  return { parentOf, agentOf };
}

// Collapse the synthetic agent ids (cache_gate, {step}_rag, summary_agent_*,
// entity_resolver) down to the canonical research step that owns the event.
export function resolveAgent(agentId, eventId, maps) {
  if (agentId === 'entity_resolver') return 'system';
  if (agentId.startsWith('summary_agent')) return 'summary_agent';
  if (agentId.endsWith('_rag')) return agentId.slice(0, -4);
  if (agentId === 'cache_gate') {
    let current = maps.parentOf.get(eventId);
    const seen = new Set();
    while (current && !seen.has(current)) {
      seen.add(current);
      const owner = maps.agentOf.get(current);
      if (owner && owner !== 'cache_gate') return resolveAgent(owner, current, maps);
      current = maps.parentOf.get(current);
    }
    return 'system';
  }
  return agentId;
}

export function groupByAgent(events) {
  const maps = buildParentMap(events);
  const groups = new Map();
  for (const event of events) {
    const key = resolveAgent(event.agent_id, event.event_id, maps);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(event);
  }
  return { groups, maps };
}

// The set of event ids on the causal path from `eventId` up to the pipeline root.
export function ancestorChain(eventId, maps) {
  const chain = new Set();
  let current = eventId;
  while (current && !chain.has(current)) {
    chain.add(current);
    current = maps.parentOf.get(current);
  }
  return chain;
}

// Every step `step` (transitively) depends on, per the dependency DAG.
export function transitiveDeps(step, dag) {
  const out = new Set();
  const stack = [...(dag?.[step] || [])];
  while (stack.length) {
    const s = stack.pop();
    if (out.has(s)) continue;
    out.add(s);
    for (const dep of (dag?.[s] || [])) stack.push(dep);
  }
  return out;
}

export function agentCounts(agentEvents) {
  let ret = 0, gen = 0, flags = 0, highFlags = 0;
  for (const event of agentEvents) {
    if (event.event_type === 'retrieval') ret += 1;
    else if (event.event_type === 'generation') gen += 1;
    else if (event.event_type === 'risk_flag') {
      flags += 1;
      const severity = String(event.payload?.severity || '').toLowerCase();
      if (severity === 'high' || severity === 'critical') highFlags += 1;
    }
  }
  return { ret, gen, flags, highFlags };
}

export function agentStatus(agentEvents) {
  const end = agentEvents.find((event) => event.event_type === 'dag_node_end');
  if (end?.status) return end.status;
  if (agentEvents.some((event) => event.status === 'failed')) return 'failed';
  return agentEvents.some((event) => event.event_type === 'dag_node_start') ? 'running' : 'recorded';
}

export function formatDuration(ms) {
  if (!Number.isFinite(ms) || ms < 0) return null;
  if (ms < 1000) return `${ms}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

// Wall-clock span of an agent, from its earliest to latest event timestamp.
export function agentDuration(agentEvents) {
  const times = agentEvents.map((event) => Date.parse(event.timestamp)).filter(Number.isFinite);
  if (times.length < 2) return null;
  return formatDuration(Math.max(...times) - Math.min(...times));
}

export function countsLabel(counts) {
  const parts = [];
  if (counts.ret) parts.push(`${counts.ret} ret`);
  if (counts.gen) parts.push(`${counts.gen} gen`);
  if (counts.flags) parts.push(`${counts.flags} flag${counts.flags > 1 ? 's' : ''}`);
  return parts.join(' · ') || 'no events';
}

export function payloadPreview(event) {
  const p = event.payload || {};
  return p.detail || p.query || p.claim || p.risk_type || `${p.findings_count ?? 0} findings`;
}

// Split an agent's events into attempts at each dag_node_start (re-runs). The last
// attempt is the accepted/final run; each earlier attempt's supersededReason is the
// replan_reason recorded on the following attempt's start.
export function segmentAttempts(agentEvents) {
  const sorted = [...agentEvents].sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp));
  const attempts = [];
  let cur = null;
  for (const e of sorted) {
    if (e.event_type === 'dag_node_start') {
      cur = { start: e, events: [e], replanReason: e.payload?.replan_reason || null };
      attempts.push(cur);
    } else if (cur) {
      cur.events.push(e);
    } else {
      cur = { start: null, events: [e], replanReason: null };
      attempts.push(cur);
    }
  }
  attempts.forEach((a, i) => {
    const end = a.events.find((e) => e.event_type === 'dag_node_end');
    a.status = end?.status || (a.events.some((e) => e.status === 'failed') ? 'failed' : 'completed');
    a.index = i;
    a.isFinal = i === attempts.length - 1;
    a.supersededReason = attempts[i + 1]?.replanReason || null;
  });
  return attempts;
}

// Dependency depth per step (0 = no dependencies), from the dependency DAG.
export function tierRanks(dag) {
  const memo = {};
  const depth = (s, stack) => {
    if (s in memo) return memo[s];
    if (stack.has(s)) return 0;
    stack.add(s);
    const deps = dag?.[s] || [];
    const d = deps.length ? 1 + Math.max(...deps.map((x) => depth(x, stack))) : 0;
    stack.delete(s);
    memo[s] = d;
    return d;
  };
  Object.keys(dag || {}).forEach((s) => depth(s, new Set()));
  return memo;
}

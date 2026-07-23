import { groupByAgent, tierRanks, segmentAttempts, agentCounts, agentStatus } from './auditModel';

const SUMMARY = 'summary';

// Build the structural model for the tiered provenance board: agents placed in
// dependency tiers, a synthetic review column (when supervisor reviews exist) between
// the last execution tier and Synthesis, and edges tagged with the routing the
// renderer applies (bus = bottom channel, feedback = dashed backward loop to re-runs).
export function buildGraphModel(events, dagDependencies, reviews = []) {
  const dag = dagDependencies || {};
  const ranks = tierRanks(dag);
  const { groups } = groupByAgent(events);

  const agents = [];
  for (const [id, evs] of groups) {
    if (id === 'system') continue;
    const attempts = segmentAttempts(evs);
    agents.push({
      id,
      tier: id === SUMMARY ? maxExecTier(dag, ranks) + 2 : (ranks[id] ?? 0),
      attempts,
      counts: agentCounts(attempts[attempts.length - 1]?.events || evs),
      status: agentStatus(evs),
    });
  }

  const hasReview = reviews.length > 0;
  const reviewTier = maxExecTier(dag, ranks) + 1;

  const tiers = [...new Set(agents.map((a) => a.tier))].sort((x, y) => x - y);
  const columns = tiers.map((t) => ({ kind: 'tier', tier: t, agents: agents.filter((a) => a.tier === t).map((a) => a.id) }));
  if (hasReview) columns.push({ kind: 'review', tier: reviewTier });
  columns.sort((a, b) => a.tier - b.tier);

  const present = new Set(agents.map((a) => a.id).filter((id) => id in dag));
  const dependedOn = new Set();
  for (const s of present) for (const d of (dag[s] || [])) if (present.has(d)) dependedOn.add(d);
  const terminals = [...present].filter((s) => !dependedOn.has(s));

  const edges = [];
  for (const a of agents) {
    if (a.id === SUMMARY) continue;
    const deps = (dag[a.id] || []).filter((d) => present.has(d));
    if (deps.length === 0) edges.push({ from: '__start__', to: a.id, kind: 'start' });
    for (const d of deps) edges.push({ from: d, to: a.id, kind: 'dep' });
  }

  const reviewTarget = hasReview ? '__review__' : SUMMARY;
  for (const t of terminals) edges.push({ from: t, to: reviewTarget, kind: 'bus' });
  if (hasReview) edges.push({ from: '__review__', to: SUMMARY, kind: 'reviewToSummary' });
  if (agents.some((a) => a.id === SUMMARY)) edges.push({ from: SUMMARY, to: '__report__', kind: 'summaryToEnd' });
  if (hasReview) {
    const reRun = new Set(reviews.flatMap((r) => (r.isAnomaly ? r.steps : [])));
    for (const s of reRun) if (present.has(s)) edges.push({ from: '__review__', to: s, kind: 'feedback' });
  }

  return { agents, columns, edges };
}

function maxExecTier(dag, ranks) {
  const execRanks = Object.entries(ranks).filter(([s]) => s in dag).map(([, r]) => r);
  return execRanks.length ? Math.max(...execRanks) : 0;
}

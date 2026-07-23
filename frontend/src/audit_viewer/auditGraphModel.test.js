import { describe, it, expect } from 'vitest';
import { buildGraphModel } from './auditGraphModel';

const dag = { shareholders: [], kyb: ['shareholders'], sanctions: ['kyb'], profile: [], media: ['profile'] };
const start = (agent, ts) => ({ event_id: agent + '-s', agent_id: agent, event_type: 'dag_node_start', timestamp: ts, payload: {} });
const end = (agent, ts) => ({ event_id: agent + '-e', agent_id: agent, event_type: 'dag_node_end', timestamp: ts, payload: {}, status: 'completed' });

describe('buildGraphModel', () => {
  it('places agents in dependency tiers and inserts a review column when reviews exist', () => {
    const events = ['shareholders', 'kyb', 'sanctions', 'profile', 'media', 'summary_agent'].flatMap((a, i) => [start(a, `2026-01-01T00:0${i}:00Z`), end(a, `2026-01-01T00:0${i}:30Z`)]);
    const reviews = [{ round: 1, isAnomaly: true, steps: ['media'], rationale: 'x' }];
    const model = buildGraphModel(events, dag, reviews);
    const byId = Object.fromEntries(model.agents.map((a) => [a.id, a]));
    expect(byId.kyb.tier).toBe(1);
    expect(byId.sanctions.tier).toBe(2);
    expect(model.columns.some((c) => c.kind === 'review')).toBe(true);
    expect(model.edges.some((e) => e.kind === 'feedback' && e.to === 'media')).toBe(true);
    expect(model.edges.some((e) => e.kind === 'reviewToSummary')).toBe(true);
  });

  it('routes terminals straight to summary when there are no reviews', () => {
    const events = ['shareholders', 'kyb', 'sanctions', 'profile', 'media', 'summary_agent'].flatMap((a, i) => [start(a, `2026-01-01T00:0${i}:00Z`), end(a, `2026-01-01T00:0${i}:30Z`)]);
    const model = buildGraphModel(events, dag, []);
    expect(model.columns.some((c) => c.kind === 'review')).toBe(false);
    expect(model.edges.some((e) => e.kind === 'feedback')).toBe(false);
    expect(model.edges.some((e) => e.kind === 'bus' && e.to === 'summary_agent')).toBe(true);
  });
});

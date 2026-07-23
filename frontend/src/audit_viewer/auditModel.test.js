import { describe, it, expect } from 'vitest';
import { segmentAttempts, tierRanks } from './auditModel';

const ev = (type, ts, extra = {}) => ({ event_type: type, timestamp: ts, payload: {}, ...extra });

describe('segmentAttempts', () => {
  it('splits an agent into attempts at each dag_node_start and marks the last final', () => {
    const events = [
      ev('dag_node_start', '2026-01-01T00:00:00Z'),
      ev('retrieval', '2026-01-01T00:00:01Z'),
      ev('dag_node_end', '2026-01-01T00:00:02Z', { status: 'failed' }),
      ev('dag_node_start', '2026-01-01T00:00:03Z', { payload: { replan_reason: 'Re-run against tier-1 outlets.' } }),
      ev('generation', '2026-01-01T00:00:04Z'),
      ev('dag_node_end', '2026-01-01T00:00:05Z', { status: 'completed' }),
    ];
    const attempts = segmentAttempts(events);
    expect(attempts).toHaveLength(2);
    expect(attempts[0].status).toBe('failed');
    expect(attempts[0].isFinal).toBe(false);
    expect(attempts[0].supersededReason).toBe('Re-run against tier-1 outlets.');
    expect(attempts[1].isFinal).toBe(true);
    expect(attempts[1].status).toBe('completed');
  });
});

describe('tierRanks', () => {
  it('computes dependency depth', () => {
    const dag = { shareholders: [], kyb: ['shareholders'], sanctions: ['kyb'], profile: [], esg: ['profile'] };
    expect(tierRanks(dag)).toEqual({ shareholders: 0, kyb: 1, sanctions: 2, profile: 0, esg: 1 });
  });
});

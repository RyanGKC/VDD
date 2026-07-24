import { describe, it, expect } from 'vitest';
import {
  segmentAttempts,
  tierRanks,
  supervisorReviews,
  contradictionRemovals,
  GLYPH,
  agentSeverityStatus,
  agentTopFlag,
  threadTree,
} from './auditModel';

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

describe('supervisorReviews', () => {
  it('extracts and orders review rounds', () => {
    const events = [
      { event_type: 'supervisor_review', timestamp: '2026-01-01T00:00:02Z', event_id: 'r2', payload: { round: 2, is_anomaly: false, rationale: 'Clear.', steps_to_run: [], updated_params: {}, verification_searches: 0 } },
      { event_type: 'supervisor_review', timestamp: '2026-01-01T00:00:01Z', event_id: 'r1', payload: { round: 1, is_anomaly: true, rationale: 'Re-run media.', steps_to_run: ['media'], updated_params: { country: 'UK' }, verification_searches: 2 } },
    ];
    const revs = supervisorReviews(events);
    expect(revs.map((r) => r.round)).toEqual([1, 2]);
    expect(revs[0].isAnomaly).toBe(true);
    expect(revs[0].steps).toEqual(['media']);
  });
});

describe('contradictionRemovals', () => {
  it('reads removed findings from the contradiction event', () => {
    const events = [{ agent_id: 'summary_agent_contradiction', event_type: 'generation', payload: { removed_findings: ['Privately held'] } }];
    expect(contradictionRemovals(events)).toEqual(['Privately held']);
  });
});

describe('GLYPH', () => {
  it('maps event types to correct unicode glyphs', () => {
    expect(GLYPH.dag_node_start).toBe('◇');
    expect(GLYPH.retrieval).toBe('⌕');
    expect(GLYPH.generation).toBe('✎');
    expect(GLYPH.risk_flag).toBe('▲');
  });
});

describe('agentSeverityStatus', () => {
  it('returns clear when no events or no risk_flag events are present', () => {
    expect(agentSeverityStatus([])).toBe('clear');
    expect(agentSeverityStatus([ev('retrieval', '2026-01-01T00:00:00Z')])).toBe('clear');
  });

  it('returns caution when low or medium risk_flag events exist', () => {
    const events = [
      ev('risk_flag', '2026-01-01T00:00:01Z', { payload: { severity: 'LOW' } }),
      ev('risk_flag', '2026-01-01T00:00:02Z', { payload: { severity: 'medium' } }),
    ];
    expect(agentSeverityStatus(events)).toBe('caution');
  });

  it('returns risk when high or critical risk_flag events exist', () => {
    const events = [
      ev('risk_flag', '2026-01-01T00:00:01Z', { payload: { severity: 'medium' } }),
      ev('risk_flag', '2026-01-01T00:00:02Z', { payload: { severity: 'HIGH' } }),
    ];
    expect(agentSeverityStatus(events)).toBe('risk');

    const criticalEvents = [
      ev('risk_flag', '2026-01-01T00:00:01Z', { payload: { severity: 'CRITICAL' } }),
    ];
    expect(agentSeverityStatus(criticalEvents)).toBe('risk');
  });
});

describe('agentTopFlag', () => {
  it('returns null when no risk_flag events exist', () => {
    expect(agentTopFlag([])).toBe(null);
    expect(agentTopFlag([ev('retrieval', '2026-01-01T00:00:00Z')])).toBe(null);
  });

  it('picks the highest severity risk_flag event', () => {
    const events = [
      ev('risk_flag', '2026-01-01T00:00:01Z', { payload: { severity: 'low', detail: 'Low risk item' } }),
      ev('risk_flag', '2026-01-01T00:00:02Z', { payload: { severity: 'critical', detail: 'Critical sanctions hit' } }),
      ev('risk_flag', '2026-01-01T00:00:03Z', { payload: { severity: 'high', detail: 'High risk finding' } }),
    ];
    const top = agentTopFlag(events);
    expect(top).toEqual({ sev: 'critical', label: 'Critical sanctions hit' });
  });

  it('resolves label fallback hierarchy (detail -> risk_type -> summary)', () => {
    const ev1 = ev('risk_flag', '2026-01-01T00:00:01Z', { payload: { severity: 'high', risk_type: 'Sanctions Violation' } });
    expect(agentTopFlag([ev1])).toEqual({ sev: 'high', label: 'Sanctions Violation' });

    const ev2 = ev('risk_flag', '2026-01-01T00:00:01Z', { summary: 'Summary label', payload: { severity: 'medium' } });
    expect(agentTopFlag([ev2])).toEqual({ sev: 'medium', label: 'Summary label' });
  });
});

describe('threadTree', () => {
  it('groups child events under their parent event id', () => {
    const events = [
      { event_id: 'e1', event_type: 'dag_node_start' },
      { event_id: 'e2', parent_event_id: 'e1', event_type: 'retrieval' },
    ];
    const tree = threadTree(events);
    expect(tree).toHaveLength(1);
    expect(tree[0].event_id).toBe('e1');
    expect(tree[0].children).toHaveLength(1);
    expect(tree[0].children[0].event_id).toBe('e2');
  });
});

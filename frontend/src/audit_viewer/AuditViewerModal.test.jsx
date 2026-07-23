import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AuditViewerModal from './AuditViewerModal';

vi.mock('reactflow', () => ({
  default: () => <div>Causal graph canvas</div>,
  Background: () => null, Controls: () => null, MiniMap: () => null,
  MarkerType: { ArrowClosed: 'arrowclosed' },
}));

const trail = {
  summary: { status: 'completed', total_events: 2, agents_completed: 1, agents_failed: 0, retrievals: 1, generations: 0, high_risk_flags: 0, evidence_events: 1 },
  entities: [{ name: 'Acme', role: 'root', event_count: 2 }], edges: [],
  dag_dependencies: { shareholders: [], kyb: ['shareholders'] },
  events: [
    { event_id: 'r1', agent_id: 'kyb', event_type: 'retrieval', timestamp: '2026-01-01T00:00:00Z', entity_name: 'Acme', entity_role: 'root', status: 'completed', payload: { query: 'Acme registry' } },
    { event_id: 'g1', agent_id: 'kyb', event_type: 'generation', timestamp: '2026-01-01T00:01:00Z', entity_name: 'Acme', entity_role: 'root', status: 'completed', payload: { claim: 'Active' } },
  ],
};

describe('AuditViewerModal', () => {
  beforeEach(() => { vi.stubGlobal('fetch', vi.fn((url) => Promise.resolve({ ok: true, json: () => Promise.resolve(String(url).includes('/chunks') ? { available: true, chunks: [{ id: 'e1', text: 'Registry excerpt', metadata: {} }] } : trail) }))); });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it('defaults to the causal graph and the root entity, then switches to the timeline', async () => {
    render(<AuditViewerModal runId="run" companyName="Acme" onClose={vi.fn()} />);
    expect(await screen.findByText('Causal graph canvas')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Causal graph' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Filter entity')).toHaveValue('Acme');
    fireEvent.click(screen.getByRole('button', { name: 'Timeline' }));
    expect(await screen.findByText('Acme registry')).toBeInTheDocument();
  });

  it('filters events and shows retained evidence from the timeline', async () => {
    render(<AuditViewerModal runId="run" companyName="Acme" onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Timeline' }));
    await screen.findByText('Acme registry');
    fireEvent.change(screen.getByLabelText('Filter event type'), { target: { value: 'retrieval' } });
    expect(screen.queryByText('Active')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Acme registry'));
    fireEvent.click(screen.getByText('View retained evidence'));
    expect(await screen.findByText('Registry excerpt')).toBeInTheDocument();
  });

  it('closes with Escape', async () => {
    const close = vi.fn(); render(<AuditViewerModal runId="run" companyName="Acme" onClose={close} />);
    await screen.findByText('Causal graph canvas'); fireEvent.keyDown(window, { key: 'Escape' });
    expect(close).toHaveBeenCalledOnce();
  });
});

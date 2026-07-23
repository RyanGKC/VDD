# Audit Causal Graph Redesign + Supervisor Surfacing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the audit-trail causal graph as a forensic "provenance ledger" (tiered lanes, custody threads, severity-only color) on React Flow, and surface the pipeline's real supervisor reviews + agent re-runs on the canvas.

**Architecture:** Backend adds a `SUPERVISOR_REVIEW` structured event and a per-attempt `replan_reason`, so review reasoning flows through the existing `/api/audit/graph` API. Frontend logic lives in pure, unit-tested functions (`auditModel.js`, new `auditGraphModel.js`); React Flow custom nodes/edges render them. The published mockup is the visual/interaction source of truth.

**Tech Stack:** Python 3 + pydantic + SQLite (`core/audit_logger.py`), FastAPI (`audit_viewer/`), React + Vite + React Flow + dagre, vitest + @testing-library/react. Tests: `./venv/bin/python -m pytest` (pytest 9.1.1 + asyncio) and `cd frontend && npx vitest run`.

## Global Constraints

- Dark-theme only (the viewer lives in the app's dark modal). Do not add a light theme.
- **Color is semantic-only:** neutral slate everywhere; saturated hue only for status/severity (clear `#3fb27f`, caution `#e0a458`, risk `#e5484d`). Event types are distinguished by monochrome glyphs + labels, never by fill color.
- Retain React Flow (keep pan/zoom). Do not replace it with a pure CSS board.
- Reuse existing helpers in `frontend/src/audit_viewer/auditModel.js`; do not duplicate grouping/duration logic.
- Every changed backend behavior must be guarded so a missing `audit_logger`/`run_id` never raises (follow the `al = getattr(ctx, 'audit_logger', None); if al and ctx.run_id:` pattern already in `base_agent.py`).
- **Visual/markup source of truth:** the published mockup HTML at `docs/superpowers/specs/` reference + artifact `provenance-ledger`. Port its DOM structure and CSS into the React components; do not invent new styling.
- Commit after every task with a `feat:`/`test:` message.

---

## Phase A — Backend: supervisor + attempt signals

### Task A1: `SUPERVISOR_REVIEW` event type + `log_supervisor_review`

**Files:**
- Modify: `core/audit_logger.py` (EventType enum ~L24; add method after `log_pipeline_end` ~L188)
- Test: `tests/test_supervisor_audit.py` (create)

**Interfaces:**
- Produces: `EventType.SUPERVISOR_REVIEW = "supervisor_review"`; `AuditLogger.log_supervisor_review(*, run_id, review_round, is_anomaly, rationale, steps_to_run, updated_params=None, verification_searches=0, parent_event_id=None, entity_name=None, entity_role=None) -> str` writing an event whose `payload` = `{round, is_anomaly, rationale, steps_to_run, updated_params, verification_searches}` and `status` = `"anomaly"`/`"clear"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_supervisor_audit.py
import asyncio, tempfile, os
from core.audit_logger import AuditLogger, EventType

def _logger():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    return AuditLogger(db_path=path), path

def test_log_supervisor_review_roundtrips():
    logger, _ = _logger()
    async def go():
        await logger.log_supervisor_review(
            run_id="run1", review_round=1, is_anomaly=True,
            rationale="Media used low-relevance sources; re-run.",
            steps_to_run=["media", "finances"], updated_params={"country": "United Kingdom"},
            verification_searches=2, entity_name="Acme", entity_role="root",
        )
    asyncio.run(go())
    events = logger._chain_for_run_sync("run1")
    assert len(events) == 1
    e = events[0]
    assert e["event_type"] == "supervisor_review"
    assert e["agent_id"] == "supervisor"
    assert e["status"] == "anomaly"
    assert e["payload"]["round"] == 1
    assert e["payload"]["steps_to_run"] == ["media", "finances"]
    assert e["payload"]["updated_params"]["country"] == "United Kingdom"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/ryangoh/VDD Prototype" && ./venv/bin/python -m pytest tests/test_supervisor_audit.py -v`
Expected: FAIL — `AttributeError: 'EventType' has no attribute 'SUPERVISOR_REVIEW'` / `log_supervisor_review`.

- [ ] **Step 3: Add the enum member**

In `core/audit_logger.py`, inside `class EventType`, after `RISK_FLAG` (L24):

```python
    RISK_FLAG = "risk_flag"            # When a finding is identified as a risk or anomaly
    SUPERVISOR_REVIEW = "supervisor_review"  # Batch QC verdict from the supervisor agent (per review round)
```

- [ ] **Step 4: Add the method**

In `core/audit_logger.py`, after `log_pipeline_end` (after L188):

```python
    async def log_supervisor_review(
        self,
        run_id: str,
        review_round: int,
        is_anomaly: bool,
        rationale: str,
        steps_to_run: list[str],
        updated_params: Optional[dict[str, Any]] = None,
        verification_searches: int = 0,
        parent_event_id: Optional[str] = None,
        entity_name: Optional[str] = None,
        entity_role: Optional[str] = None,
    ) -> str:
        """Logs one batched supervisor review round (anomaly verdict + re-plan)."""
        return await self.log(
            AuditEvent(
                run_id=run_id,
                agent_id="supervisor",
                event_type=EventType.SUPERVISOR_REVIEW,
                parent_event_id=parent_event_id,
                entity_name=entity_name,
                entity_role=entity_role,
                status="anomaly" if is_anomaly else "clear",
                payload={
                    "round": review_round,
                    "is_anomaly": is_anomaly,
                    "rationale": rationale,
                    "steps_to_run": steps_to_run,
                    "updated_params": updated_params or {},
                    "verification_searches": verification_searches,
                },
            )
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd "/Users/ryangoh/VDD Prototype" && ./venv/bin/python -m pytest tests/test_supervisor_audit.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/audit_logger.py tests/test_supervisor_audit.py
git commit -m "feat(audit): add SUPERVISOR_REVIEW event type and logger"
```

---

### Task A2: carry `replan_reason` on the re-run's `DAG_NODE_START`

**Files:**
- Modify: `core/audit_logger.py` `log_dag_node` (L190-230)
- Modify: `agents/base_agent.py` DAG_NODE_START call (L338-345)
- Test: `tests/test_supervisor_audit.py` (append)

**Interfaces:**
- Consumes: `EventType` (A1).
- Produces: `log_dag_node(..., replan_reason: Optional[str] = None)` — when set, adds `payload["replan_reason"]`. `base_agent.run()` passes `replan_reason=ctx._replan_rationale.get(step)` on DAG_NODE_START.

- [ ] **Step 1: Write the failing test** (append to `tests/test_supervisor_audit.py`)

```python
from core.audit_logger import AuditLogger, EventType  # already imported above

def test_dag_node_carries_replan_reason():
    logger, _ = _logger()
    async def go():
        await logger.log_dag_node(
            run_id="run2", agent_id="media", event_type=EventType.DAG_NODE_START,
            replan_reason="Re-run against tier-1 outlets.",
        )
    asyncio.run(go())
    e = logger._chain_for_run_sync("run2")[0]
    assert e["payload"]["replan_reason"] == "Re-run against tier-1 outlets."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/ryangoh/VDD Prototype" && ./venv/bin/python -m pytest tests/test_supervisor_audit.py::test_dag_node_carries_replan_reason -v`
Expected: FAIL — `TypeError: log_dag_node() got an unexpected keyword argument 'replan_reason'`.

- [ ] **Step 3: Add the param** — in `core/audit_logger.py` `log_dag_node`, add `replan_reason: Optional[str] = None,` to the signature (after `status`), and extend the payload build (replace L216-218):

```python
        payload = {"findings_count": findings_count}
        if anomaly:
            payload["anomaly"] = anomaly
        if replan_reason:
            payload["replan_reason"] = replan_reason
```

- [ ] **Step 4: Pass it from base_agent** — in `agents/base_agent.py`, the DAG_NODE_START call (L338-345) becomes:

```python
            start_event_id = await al.log_dag_node(
                run_id=ctx.run_id,
                agent_id=self.step.value,
                event_type=EventType.DAG_NODE_START,
                parent_event_id=pipeline_start_event_id,
                entity_name=ctx.company_details.company_name,
                entity_role=ctx.entity_role,
                replan_reason=getattr(ctx, '_replan_rationale', {}).get(self.step.value),
            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "/Users/ryangoh/VDD Prototype" && ./venv/bin/python -m pytest tests/test_supervisor_audit.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add core/audit_logger.py agents/base_agent.py tests/test_supervisor_audit.py
git commit -m "feat(audit): record supervisor replan reason on re-run DAG_NODE_START"
```

---

### Task A3: emit a review event per round from the supervisor

**Files:**
- Modify: `agents/supervisor_agent.py` `review()` (signature L91-96; after `ctx.audit(...rationale)` L204)
- Modify: `core/flow_engine.py` `run()` (review call L171-198)
- Test: `tests/test_supervisor_audit.py` (append)

**Interfaces:**
- Consumes: `AuditLogger.log_supervisor_review` (A1).
- Produces: `SupervisorAgent.review(*, ctx, completed, review_round: int = 1)` logs one `SUPERVISOR_REVIEW` event per call (both anomaly and clear). `FlowEngine.run` passes an incrementing `review_round`.

- [ ] **Step 1: Write the failing test** (append). This drives a minimal fake ctx.

```python
class _FakeCtx:
    def __init__(self, logger, run_id):
        self.audit_logger = logger; self.run_id = run_id
        self.entity_role = "root"; self.audit_pipeline_event_id = None
        self.results = {}; self.enrichment = {}; self.execution_log = []
        class _CD: company_name = "Acme"
        self.company_details = _CD()
    def log(self, *a, **k): pass
    def audit(self, *a, **k): pass

def test_supervisor_logs_review_event(monkeypatch):
    logger, _ = _logger()
    from agents import supervisor_agent as sa
    # Stub the LLM + neo4j so review() runs offline and returns a clear decision.
    async def fake_gen(**kwargs):
        schema = kwargs["schema"]
        if schema is sa._ReviewPlan: return sa._ReviewPlan(research_plan=[])
        return sa._ReviewDecision(is_anomaly=False, rationale="All consistent.", steps_to_run=[])
    class _Client: 
        async def generate_structured(self, **k): return await fake_gen(**k)
    monkeypatch.setattr(sa, "run_foreground_generation", lambda fn: fn(), raising=False)
    class _Neo:
        async def get_risky_neighbors(self, *a, **k): return []
    import core.dependencies as deps
    monkeypatch.setattr(deps, "neo4j", _Neo(), raising=False)

    sup = sa.SupervisorAgent(_Client())
    ctx = _FakeCtx(logger, "run3")
    asyncio.run(sup.review(ctx=ctx, completed=set(), review_round=1))
    revs = [e for e in logger._chain_for_run_sync("run3") if e["event_type"] == "supervisor_review"]
    assert len(revs) == 1 and revs[0]["payload"]["is_anomaly"] is False
```

> Note: `run_foreground_generation` is imported inside `review()` via `from rag.rate_limiter import run_foreground_generation`. Patch it on `agents.supervisor_agent` only if that import is module-level; otherwise patch `rag.rate_limiter.run_foreground_generation`. Verify the failing run's error message and adjust the monkeypatch target accordingly before implementing.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/ryangoh/VDD Prototype" && ./venv/bin/python -m pytest tests/test_supervisor_audit.py::test_supervisor_logs_review_event -v`
Expected: FAIL — no `supervisor_review` events (assert length 1 fails), or `TypeError` for unexpected `review_round`.

- [ ] **Step 3: Add `review_round` param** — in `agents/supervisor_agent.py`, change the signature (L91-96):

```python
    async def review(
        self,
        *,
        ctx: DDContext,
        completed: set[StepName],
        review_round: int = 1,
    ) -> tuple[list[StepName], bool]:
```

- [ ] **Step 4: Log the review** — immediately after `ctx.audit(f"[SUPERVISOR] Decision Rationale:\n{decision.rationale}")` (L204), insert:

```python
        al = getattr(ctx, 'audit_logger', None)
        if al and getattr(ctx, 'run_id', None):
            await al.log_supervisor_review(
                run_id=ctx.run_id,
                review_round=review_round,
                is_anomaly=decision.is_anomaly,
                rationale=decision.rationale,
                steps_to_run=[s.value for s in decision.steps_to_run],
                updated_params={k: v for k, v in {
                    "country": decision.updated_country,
                    "registration_number": decision.updated_registration_number,
                    "address": decision.updated_address,
                    "website": decision.updated_website,
                    "tax_id": decision.updated_tax_id,
                }.items() if v},
                verification_searches=len(queries),
                parent_event_id=getattr(ctx, 'audit_pipeline_event_id', None),
                entity_name=ctx.company_details.company_name,
                entity_role=getattr(ctx, 'entity_role', None),
            )
```

- [ ] **Step 5: Pass the round from FlowEngine** — in `core/flow_engine.py` `run()`, add `review_round = 0` just before the `while plan:` loop (after L155), then inside the loop where the review is dispatched (L171-198) increment and pass it. Replace L171-174:

```python
            # 2. Batched Supervisor Review & Speculative Contradiction Detection
            ctx.log("SUPERVISOR batch reviewing all completed results...")
            review_round += 1

            import asyncio
            supervisor_task = self._supervisor.review(ctx=ctx, completed=all_completed, review_round=review_round)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd "/Users/ryangoh/VDD Prototype" && ./venv/bin/python -m pytest tests/test_supervisor_audit.py -v`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add agents/supervisor_agent.py core/flow_engine.py tests/test_supervisor_audit.py
git commit -m "feat(supervisor): log a SUPERVISOR_REVIEW event per review round"
```

---

### Task A4: log contradiction removals with the dropped findings

**Files:**
- Modify: `core/audit_logger.py` `log_generation` (L281-324) — add `extra` param
- Modify: `agents/summary_agent.py` contradiction logging (L183-206)
- Test: `tests/test_supervisor_audit.py` (append)

**Interfaces:**
- Produces: `log_generation(..., extra: Optional[dict] = None)` merges `extra` into payload. The `summary_agent_contradiction` GENERATION event's payload gains `removed_findings: list[str]`.

- [ ] **Step 1: Write the failing test** (append)

```python
def test_generation_extra_merges_into_payload():
    logger, _ = _logger()
    async def go():
        await logger.log_generation(
            run_id="run4", agent_id="summary_agent_contradiction",
            claim="Contradiction check", supporting_chunk_ids=[], model_version="x",
            extra={"removed_findings": ["Company is privately held"]},
        )
    asyncio.run(go())
    e = logger._chain_for_run_sync("run4")[0]
    assert e["payload"]["removed_findings"] == ["Company is privately held"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/ryangoh/VDD Prototype" && ./venv/bin/python -m pytest tests/test_supervisor_audit.py::test_generation_extra_merges_into_payload -v`
Expected: FAIL — unexpected keyword `extra`.

- [ ] **Step 3: Add `extra` to `log_generation`** — add `extra: Optional[dict[str, Any]] = None,` to the signature, and build the payload (replace the `payload={...}` block at L319-322):

```python
                payload={
                    "claim": claim,
                    "supporting_chunk_ids": supporting_chunk_ids,
                    **(extra or {}),
                },
```

- [ ] **Step 4: Attach removed findings** — in `agents/summary_agent.py`, move the contradiction logging to after `cleaned_findings` is computed and pass the removed summaries. Replace L183-206 with:

```python
        if removal_indices:
            ctx.log(
                f"SUMMARY: Removed {len(removal_indices)} contradictory "
                f"finding(s): indices {removal_indices}"
            )
            cleaned_findings = [
                f for i, f in enumerate(all_findings)
                if i not in set(removal_indices)
            ]
        else:
            cleaned_findings = all_findings

        if al and detect_res:
            import json
            removed = [all_findings[i].summary for i in removal_indices if i < len(all_findings)]
            await al.log_generation(
                run_id=ctx.run_id,
                agent_id="summary_agent_contradiction",
                claim=f"Contradiction check results: {json.dumps(detect_res.model_dump())}",
                supporting_chunk_ids=[],
                model_version=getattr(self.gemini, '_model', 'unknown'),
                parent_event_id=start_event_id,
                entity_name=ctx.company_details.company_name,
                entity_role=ctx.entity_role,
                extra={"removed_findings": removed},
            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "/Users/ryangoh/VDD Prototype" && ./venv/bin/python -m pytest tests/test_supervisor_audit.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/audit_logger.py agents/summary_agent.py tests/test_supervisor_audit.py
git commit -m "feat(audit): record removed findings on the contradiction-check event"
```

---

## Phase B — Frontend model (pure, unit-tested)

All Phase B functions are pure and live in `frontend/src/audit_viewer/`. Run tests with `cd frontend && npx vitest run src/audit_viewer/<file>`.

### Task B1: attempt segmentation + tier ranks

**Files:**
- Modify: `frontend/src/audit_viewer/auditModel.js` (append exports)
- Test: `frontend/src/audit_viewer/auditModel.test.js` (create)

**Interfaces:**
- Produces:
  - `segmentAttempts(agentEvents) -> Attempt[]` where `Attempt = { start, events, status, replanReason, supersededReason, index, isFinal }`. Splits an agent's events into attempts at each `dag_node_start` (timestamp order); the last is `isFinal`; each non-final attempt's `supersededReason` = the next attempt's `replanReason`.
  - `tierRanks(dag) -> { [step]: number }` — dependency depth per step (0 = no deps).

- [ ] **Step 1: Write the failing tests**

```js
// frontend/src/audit_viewer/auditModel.test.js
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/audit_viewer/auditModel.test.js`
Expected: FAIL — `segmentAttempts is not a function`.

- [ ] **Step 3: Implement** — append to `frontend/src/audit_viewer/auditModel.js`:

```js
// Split an agent's events into attempts at each dag_node_start (re-runs).
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

// Dependency depth per step (0 = no dependencies).
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/audit_viewer/auditModel.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/audit_viewer/auditModel.js frontend/src/audit_viewer/auditModel.test.js
git commit -m "feat(audit-ui): attempt segmentation and dependency tier ranks"
```

---

### Task B2: supervisor reviews + contradiction extraction

**Files:**
- Modify: `frontend/src/audit_viewer/auditModel.js` (append)
- Test: `frontend/src/audit_viewer/auditModel.test.js` (append)

**Interfaces:**
- Produces:
  - `supervisorReviews(events) -> Review[]`, `Review = { round, isAnomaly, rationale, steps, updatedParams, verificationSearches, eventId }` (timestamp-sorted).
  - `contradictionRemovals(events) -> string[]` from the `summary_agent_contradiction` generation payload.

- [ ] **Step 1: Write the failing tests** (append)

```js
import { supervisorReviews, contradictionRemovals } from './auditModel';

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
```

- [ ] **Step 2: Run to verify fail** — `cd frontend && npx vitest run src/audit_viewer/auditModel.test.js` → FAIL (not functions).

- [ ] **Step 3: Implement** (append to `auditModel.js`)

```js
export function supervisorReviews(events) {
  return events
    .filter((e) => e.event_type === 'supervisor_review')
    .sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp))
    .map((e) => ({
      round: e.payload.round,
      isAnomaly: e.payload.is_anomaly,
      rationale: e.payload.rationale,
      steps: e.payload.steps_to_run || [],
      updatedParams: e.payload.updated_params || {},
      verificationSearches: e.payload.verification_searches || 0,
      eventId: e.event_id,
    }));
}

export function contradictionRemovals(events) {
  const e = events.find((x) => x.agent_id === 'summary_agent_contradiction' && x.event_type === 'generation');
  return e?.payload?.removed_findings || [];
}
```

- [ ] **Step 4: Run to verify pass** — same command → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/audit_viewer/auditModel.js frontend/src/audit_viewer/auditModel.test.js
git commit -m "feat(audit-ui): extract supervisor reviews and contradiction removals"
```

---

### Task B3: tiered graph model builder

**Files:**
- Create: `frontend/src/audit_viewer/auditGraphModel.js`
- Test: `frontend/src/audit_viewer/auditGraphModel.test.js`

**Interfaces:**
- Consumes: `groupByAgent`, `tierRanks`, `supervisorReviews`, `ancestorChain`, `transitiveDeps` from `auditModel.js`.
- Produces: `buildGraphModel(events, dagDependencies, reviews) -> { agents, columns, edges }` where `agents = [{ id, tier, attempts, counts, status }]` (via `segmentAttempts`/`agentCounts`), `columns` groups agent ids by tier plus a synthetic `review` column between the max execution tier and the summary tier when `reviews.length > 0`, and `edges = [{ from, to, kind }]` with `kind ∈ {'dep','start','toReview','reviewToSummary','summaryToEnd','feedback','bus'}`. `bus`/`feedback` mark the routing the renderer applies (bottom channel / dashed backward loop). This is the structural model; pixel layout is applied by the renderer (Task C2) via dagre + custom positioning, mirroring the mockup's `edges()`/`drawWires()`.

- [ ] **Step 1: Write the failing test**

```js
// frontend/src/audit_viewer/auditGraphModel.test.js
import { describe, it, expect } from 'vitest';
import { buildGraphModel } from './auditGraphModel';

const dag = { shareholders: [], kyb: ['shareholders'], sanctions: ['kyb'], profile: [], media: ['profile'] };
const start = (agent, ts) => ({ event_id: agent + '-s', agent_id: agent, event_type: 'dag_node_start', timestamp: ts, payload: {} });
const end = (agent, ts) => ({ event_id: agent + '-e', agent_id: agent, event_type: 'dag_node_end', timestamp: ts, payload: {}, status: 'completed' });

it('places agents in dependency tiers and inserts a review column when reviews exist', () => {
  const events = ['shareholders', 'kyb', 'sanctions', 'profile', 'media', 'summary'].flatMap((a, i) => [start(a, `2026-01-01T00:0${i}:00Z`), end(a, `2026-01-01T00:0${i}:30Z`)]);
  const reviews = [{ round: 1, isAnomaly: true, steps: ['media'], rationale: 'x' }];
  const model = buildGraphModel(events, dag, reviews);
  const byId = Object.fromEntries(model.agents.map((a) => [a.id, a]));
  expect(byId.kyb.tier).toBe(1);
  expect(byId.sanctions.tier).toBe(2);
  // A review column exists and feedback edges target the re-run agents.
  expect(model.columns.some((c) => c.kind === 'review')).toBe(true);
  expect(model.edges.some((e) => e.kind === 'feedback' && e.to === 'media')).toBe(true);
  expect(model.edges.some((e) => e.kind === 'reviewToSummary')).toBe(true);
});
```

- [ ] **Step 2: Run to verify fail** — `cd frontend && npx vitest run src/audit_viewer/auditGraphModel.test.js` → FAIL (module missing).

- [ ] **Step 3: Implement** — create `frontend/src/audit_viewer/auditGraphModel.js`. Port the mockup's grouping/edge logic (`edges()` in the mockup) into this pure builder:

```js
import { groupByAgent, tierRanks, segmentAttempts, agentCounts, agentStatus } from './auditModel';

const SUMMARY = 'summary';

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

  // Columns: execution tiers, then (optional) review, then summary/output.
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
  // Terminals feed the review lane (or summary directly when no reviews).
  const reviewTarget = hasReview ? '__review__' : SUMMARY;
  for (const t of terminals) edges.push({ from: t, to: reviewTarget, kind: 'bus' });
  if (hasReview) edges.push({ from: '__review__', to: SUMMARY, kind: 'reviewToSummary' });
  if (agents.some((a) => a.id === SUMMARY)) edges.push({ from: SUMMARY, to: '__report__', kind: 'summaryToEnd' });
  // Feedback loops: each anomaly round re-ran some steps.
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
```

- [ ] **Step 4: Run to verify pass** — same command → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/audit_viewer/auditGraphModel.js frontend/src/audit_viewer/auditGraphModel.test.js
git commit -m "feat(audit-ui): tiered graph model with review lane and feedback edges"
```

---

## Phase C — Frontend rendering (React Flow)

The mockup is the pixel/markup/interaction reference. Port its CSS and node DOM verbatim; wire behavior to the Phase B model.

### Task C1: styles

**Files:**
- Modify: `frontend/src/audit_viewer/AuditViewer.css`

- [ ] **Step 1: Port the mockup styles** — copy the mockup's design tokens and component classes into `AuditViewer.css` under a clearly commented `/* ── Provenance ledger redesign ── */` section: the `--canvas/--surface/--line/--ink/--clear/--caution/--risk` custom properties; `.audit-node-agent` (case card) with the status spine, title, count tokens, risk chip; `.audit-thread` custody rail + `.audit-node-event`; `.audit-attempt` (superseded/failed collapsible) + `.audit-accepted-lab`; `.audit-review-node` (dashed); and `.audit-sup-round`/`.audit-sup-steps` for the side panel. Keep every hue semantic per Global Constraints.

- [ ] **Step 2: Verify build** — `cd frontend && npx vite build` → builds with no CSS errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/audit_viewer/AuditViewer.css
git commit -m "style(audit-ui): provenance-ledger tokens and node styles"
```

---

### Task C2: rewrite `AuditGraph.jsx` on the tiered model

**Files:**
- Modify: `frontend/src/audit_viewer/AuditGraph.jsx`
- Modify: `frontend/src/audit_viewer/AuditViewerModal.jsx` (pass `reviews` prop)

**Interfaces:**
- Consumes: `buildGraphModel` (B3), `supervisorReviews` (B2), `ancestorChain`/`transitiveDeps` (auditModel). Props: `events`, `dagDependencies`, `selectedId`, `onNodeClick`, `collapseTrigger`, `reviews`.
- Produces: React Flow nodes/edges. Node types: `agent` (case card with attempts + custody thread), `review` (supervisor lane node), `pipeline` (start/report). Edges: a custom `bus` edge (bottom-channel routing) + default for `dep`/`start`. Clicking an agent expands its custody thread; clicking a thread event calls `onNodeClick(event_id)`; clicking the review node calls `onNodeClick('__review__')`.

- [ ] **Step 1: Replace the node/edge construction** — rebuild `AuditGraph.jsx` so its `useMemo` calls `buildGraphModel(events, dagDependencies, reviews)` and maps `model.agents`/`model.columns`/`model.edges` to React Flow nodes/edges. Assign node `position` from tier→column index (x) and within-column order (y), matching the mockup's layout; keep `dagre` only for within-agent thread layout (reuse the existing `layoutAgentSubgraph`). Custom node components render the mockup DOM:
  - `AgentCardNode` — collapsed: name, duration, count tokens, risk chip, and a `⟲ N re-run` token when `attempts.length > 1`; expanded: superseded attempts (collapsible, via `segmentAttempts`, showing `supersededReason`), the `✓ Accepted run` label, and the final attempt's custody thread built from `parent_event_id`.
  - `ReviewLaneNode` — the dashed "⚖ Supervisor" node; shows round count + anomaly count from `reviews`.
  - `PipelineNode` — start/report.
  Focus/ancestry illumination and dimming reuse the current selection logic (ancestry via `ancestorChain`, prerequisite agents via `transitiveDeps`), plus dashed amber `feedback` edges from the review node to re-run agents.

  Keep the whole component ≤ ~450 lines; if the custom node components push past that, split them into `frontend/src/audit_viewer/AuditGraphNodes.jsx`.

- [ ] **Step 2: Pass `reviews` from the modal** — in `AuditViewerModal.jsx`, compute `const reviews = useMemo(() => supervisorReviews(data?.events || []), [data]);` and pass `reviews={reviews}` to `<AuditGraph>`.

- [ ] **Step 3: Verify build + existing tests** — `cd frontend && npx vite build && npx vitest run` → build passes; existing modal tests still pass (reactflow is mocked, so graph internals don't break tests).

- [ ] **Step 4: Manual visual check** — run the app, open a real run's Audit Trail, confirm: tiered lanes render, an agent expands into a custody thread, a re-run agent shows a superseded attempt + reason, the supervisor review node sits before Synthesis with dashed feedback edges. Compare against the mockup.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/audit_viewer/AuditGraph.jsx frontend/src/audit_viewer/AuditViewerModal.jsx frontend/src/audit_viewer/AuditGraphNodes.jsx
git commit -m "feat(audit-ui): tiered provenance board with attempts and supervisor lane"
```

---

### Task C3: side panel — supervisor review + attempt detail

**Files:**
- Modify: `frontend/src/audit_viewer/AuditSidePanel.jsx`
- Modify: `frontend/src/audit_viewer/AuditViewerModal.jsx` (handle `__review__` selection)

**Interfaces:**
- Consumes: `reviews` (B2), `contradictionRemovals` (B2). When `selectedId === '__review__'`, the panel renders the review timeline; otherwise the existing event detail + evidence.

- [ ] **Step 1: Render the review timeline** — extend `AuditSidePanel.jsx` to accept `reviews` and `contradictions` props and, when the modal passes a `review` view flag (selected id `'__review__'`), render the round-by-round timeline (verdict pill, rationale, re-ran steps, param corrections) + a "Contradiction check" section listing `contradictions`. Port the mockup's `renderSupervisor()` markup and `.audit-sup-round` styles.

- [ ] **Step 2: Wire selection** — in `AuditViewerModal.jsx`, when `selectedId === '__review__'`, render the supervisor panel branch; pass `reviews` and `contradictionRemovals(data.events)`.

- [ ] **Step 3: Verify build + tests** — `cd frontend && npx vite build && npx vitest run` → pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/audit_viewer/AuditSidePanel.jsx frontend/src/audit_viewer/AuditViewerModal.jsx
git commit -m "feat(audit-ui): supervisor review timeline in the side panel"
```

---

### Task C4: integration tests

**Files:**
- Modify: `frontend/src/audit_viewer/AuditViewerModal.test.jsx`

**Interfaces:**
- Consumes: the full modal. The reactflow mock must expose `MarkerType` (already added) and any React Flow exports the new `AuditGraph` imports (e.g., `Handle`, `Position`) — extend the mock as needed.

- [ ] **Step 1: Extend the fixture + tests** — add `supervisor_review` events and a two-attempt agent to the `trail` fixture, then assert: (a) `supervisorReviews`/`segmentAttempts` drive visible output via the modal (switch to Timeline to read event text under the mocked graph), (b) selecting a retrieval still loads evidence, (c) the entity switcher still defaults to root. Extend the `vi.mock('reactflow', …)` with any newly imported exports so the graph renders under test.

```js
// add to the trail fixture:
dag_dependencies: { shareholders: [], kyb: ['shareholders'] },
events: [
  ...existing,
  { event_id: 'sup1', agent_id: 'supervisor', event_type: 'supervisor_review', timestamp: '2026-01-01T00:02:00Z', entity_name: 'Acme', entity_role: 'root', status: 'anomaly', payload: { round: 1, is_anomaly: true, rationale: 'Re-run kyb.', steps_to_run: ['kyb'], updated_params: {}, verification_searches: 1 } },
],
```

- [ ] **Step 2: Run tests** — `cd frontend && npx vitest run src/audit_viewer/` → PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/audit_viewer/AuditViewerModal.test.jsx
git commit -m "test(audit-ui): cover supervisor events and multi-attempt agents"
```

---

### Task D: full verification + graph refresh

- [ ] **Step 1: Backend suite** — `cd "/Users/ryangoh/VDD Prototype" && ./venv/bin/python -m pytest tests/test_supervisor_audit.py tests/test_audit_trail.py -v` → PASS.
- [ ] **Step 2: Frontend suite + build** — `cd frontend && npx vitest run && npx vite build && npx eslint src/audit_viewer` → all pass, lint clean.
- [ ] **Step 3: End-to-end spot check** — run a real pipeline (or a fixture with a forced anomaly), open the Audit Trail, and confirm the `/api/audit/graph` response includes `supervisor_review` events and a re-run agent with two `DAG_NODE_START`s (the later carrying `replan_reason`), and that all of it renders per the mockup.
- [ ] **Step 4: Refresh the knowledge graph** — `graphify update .`
- [ ] **Step 5: Commit any remaining changes**

```bash
git add -A && git commit -m "chore: refresh graphify after audit causal graph redesign"
```

---

## Self-review notes

- **Spec coverage:** Part 1 visual redesign → Tasks C1–C2 (+ B1/B3). Part 2 backend (SUPERVISOR_REVIEW, replan_reason, contradiction removals) → A1–A4. Part 2 frontend (multi-attempt segmentation, on-board review lane, review timeline) → B1/B2/B3, C2, C3. Resolved decisions (on-board lane, replan_reason on next attempt's DAG_NODE_START, React Flow retained) are reflected in A2, B3, C2.
- **Types:** `segmentAttempts` fields (`replanReason`, `supersededReason`, `isFinal`) are consumed only in C2; `buildGraphModel` edge `kind`s are consumed only in C2's renderer; `supervisorReviews` shape is consumed in C2/C3. Names are consistent across tasks.
- **Known soft spots to verify during execution:** the monkeypatch target in A3 (module-level vs local import of `run_foreground_generation`); the exact React Flow exports the rewritten `AuditGraph` imports (extend the test mock accordingly in C4).

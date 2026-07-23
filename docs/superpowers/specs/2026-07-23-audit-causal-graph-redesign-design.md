# Audit Causal Graph — Redesign + Supervisor Surfacing

**Date:** 2026-07-23
**Status:** Design — awaiting review before implementation

## Context & goal

The audit-trail viewer proves *why the report says what it says*. The current causal graph uses a rainbow of decorative colors, animated edges, a free-form dagre layout, and per-agent nodes that expand into a hard-to-read node-soup. It also ignores a real dimension of the pipeline: agents are **reviewed by a supervisor and sometimes re-run**, and none of that is visible.

This project has two parts, both approved via an interactive mockup (`provenance-ledger` artifact):

1. **Visual redesign** — reframe the graph as a *forensic provenance ledger*: severity-only color, tiered dependency lanes, and case cards that expand into a linear "custody thread." Frontend-only, against data we already have.
2. **Supervisor surfacing (full scope)** — make the supervisor's review and agent re-runs first-class in the audit trail: segment each agent's multiple attempts, log the supervisor's review rounds as structured events, and surface contradiction removals. Backend + frontend.

## What the pipeline actually does (investigation findings)

- **`SupervisorAgent.review()`** (`agents/supervisor_agent.py:91`) reviews the **whole batch** of completed steps at once, optionally runs up to 3 verification web searches, and returns `(steps_to_run, is_anomaly)` with a `rationale`, optional corrected params, and `new_enrichment`. There is **no per-agent "accepted" verdict** — "accepted" simply means a review round returned `is_anomaly=False`.
- **`FlowEngine.run()`** (`core/flow_engine.py:142`) loops: execute DAG → supervisor review → if anomaly, re-plan the named steps (max `MAX_REPLANS=5`). Crashes get an immediate localized retry (`_execute_dag`, max 3); on exhaustion a failed `StepResult` is injected.
- **Every re-run calls `agent.run()` again**, which logs a fresh `DAG_NODE_START → DAG_NODE_END` pair (`base_agent.py:338, 457`). So **multiple attempts per agent already exist in `structured_audit.db`**, ordered by timestamp. Crash attempts carry `status="failed"` + anomaly (`base_agent.py:359-362`).
- On re-run, the agent is fed *"SUPERVISOR FEEDBACK FROM PREVIOUS FAILED ATTEMPT"* from `ctx._replan_rationale[step]` (`base_agent.py:133-135`) — but this reason is **not logged to the structured audit**. It lives only in the legacy text audit (`ctx.audit`), in-memory, and the `interventions` checkpoint table (`checkpoint_db.py:159`).
- The graph API (`audit_viewer/services.py:27`) reads **only** the structured events, so today the frontend can see *that* an agent re-ran but not *why*.

**Verdict:** multi-attempt data is real and already present; the supervisor's reasoning needs a small structured-logging bridge to reach the graph; per-agent accept/reject stamps are not real and are replaced by run-level review rounds.

## Design

### Part 1 — Visual redesign (frontend)

Rebuild the graph view **on top of the existing React Flow canvas** (retaining pan/zoom for large/multi-entity runs), porting the mockup's visual language into React Flow custom nodes + custom edges. Reuse the data wiring and `auditModel.js` helpers already built.

- **Tiered lanes** by dependency depth (Sourcing → Verification → Screening → **Supervisor review** → Synthesis), sourced from `dag_dependencies`. Deterministic, scannable. React Flow node ranks/positions are assigned per tier (dagre or manual), with the review lane occupying its own rank between Screening and Synthesis.
- **Hairline S-curve connectors** as custom React Flow edges; long "skip" edges toward the review lane / Synthesis run through a dedicated **bottom bus channel** so no card obscures them. Motion only on selection; `prefers-reduced-motion` respected.
- **Severity-only color.** Neutral slate throughout; the sole saturated hues are status/severity (clear/caution/risk) on a card's left spine + chips. Event types are told apart by monochrome glyphs + labels, not color.
- **Case cards** (collapsed): name, duration, monospace count tokens (`⌕ 3`, `✎ 2`), a risk chip only when flags exist.
- **Custody thread** (expanded): the agent's causal chain rendered as an indented, rail-connected thread (start → retrieval → generation → ▲ risk), built from real `parent_event_id` edges. Clicking a step opens the side panel (detail + retained evidence) and **illuminates its ancestry** while dimming the rest.
- **Side panel** defaults to a **priority-findings** list (severity-sorted) that jumps to the evidence.
- **Deselect** (re-click node, collapse card, or Collapse All) returns to the neutral default.
- Dark-committed by design (lives in the app's dark modal). Real fonts in production: IBM Plex Mono (data) + Space Grotesk (labels), inlined.

Files: rewrite the React Flow node/edge layer in `AuditGraph.jsx` (new custom node components for case cards, custody-thread content, the review-lane node; custom bottom-bus edges), extend `auditModel.js` (attempt segmentation, tier ranks), restyle `AuditViewer.css`, keep `AuditSidePanel.jsx` + evidence drill-down, keep the entity switcher/toolbar in `AuditViewerModal.jsx`.

### Part 2 — Supervisor surfacing

**Backend**

1. **New structured event type `SUPERVISOR_REVIEW`** (`core/audit_logger.py` `EventType` + a `log_supervisor_review(...)` method). Emit one per review round from inside `SupervisorAgent.review()` right after the decision is computed (`supervisor_agent.py:~203`), parented to the pipeline start. Payload:
   `{ round, is_anomaly, rationale, steps_to_run: [...], updated_params: {...}, verification_searches: n }`.
   This flows through the existing graph API automatically (it's just another event in `events`).
2. **Re-run reason on attempts.** When a step re-runs, include the supervisor rationale + attempt marker on that attempt's `DAG_NODE_START` payload (extend `base_agent.py:133/338` to add `payload.replan_reason` and `payload.replan_round`). This lets the frontend attach *why* attempt N-1 was superseded.
3. **Contradiction removals.** Surface the findings dropped by `_detect_contradictions` (`flow_engine.py:190`) — log a structured event (or extend the existing `summary_agent_contradiction` GENERATION payload) capturing `{ removed: [{finding, reason}] }` so the UI can show what was pruned and why.
4. The `interventions` checkpoint table becomes redundant with (1) for display purposes and is **not** separately exposed — noted as a deliberate simplification.

**Frontend**

1. **Multi-attempt segmentation.** Group each agent's events into attempts by `DAG_NODE_START` boundaries (timestamp order). The **final attempt is the prominent "accepted" run**; earlier attempts render as collapsed sections labeled **failed** (crash, `status="failed"`) or **superseded** (supervisor re-plan), each showing its `replan_reason`. A `⟲ N re-run` token appears on the collapsed card.
2. **On-board Supervisor review lane.** A dedicated lane/node sits **between Screening and Synthesis**, built from the `SUPERVISOR_REVIEW` events. Execution terminals feed *into* the review node; the review node feeds Synthesis; and each anomaly round draws **dashed feedback edges back to the agents it re-ran**, making the review→re-run loop visible on the canvas. Selecting the review node opens the round-by-round detail (verdict, rationale, re-planned steps, param corrections) plus the **contradiction-check** entry in the side panel. Re-run agents also get a `re-run · R1` badge and their superseded attempts inline.

### Data-flow summary

`FlowEngine` → `SupervisorAgent.review()` logs `SUPERVISOR_REVIEW` events + agents log per-attempt `DAG_NODE_*` (with `replan_reason`) → `structured_audit.db` → `build_audit_graph` returns them in `events` (+ `dag_dependencies` already added) → frontend segments attempts, builds the tiered board, and renders the supervisor timeline.

## Testing / verification

- **Backend:** unit-test `log_supervisor_review` writes/reads an event; run a pipeline with a forced anomaly (or a fixture) and assert the `/api/audit/graph` response contains `SUPERVISOR_REVIEW` events and a re-run agent with two `DAG_NODE_START`s, the later carrying `replan_reason`.
- **Frontend:** extend `AuditViewerModal.test.jsx` — assert (a) the tiered board renders agents by `dag_dependencies`, (b) an agent with two attempts shows a collapsed superseded attempt + prominent accepted run, (c) the supervisor review timeline lists rounds with verdict + rationale, (d) selecting a node illuminates ancestry and populates evidence, (e) deselect resets. `npm test` + `vite build` pass.
- Run `graphify update .` after code changes.

## Scope / sequencing

- Part 1 (visual redesign) is independent and can land first.
- Part 2 backend (structured supervisor events) unblocks Part 2 frontend.
- Out of scope: exposing the raw `interventions` table; multi-entity hierarchy nesting; a positional time axis (durations shown on cards/threads instead).

## Resolved decisions

1. **Supervisor placement** — a **dedicated on-board review lane** between Screening and Synthesis, with dashed feedback edges to re-run agents. (Not a side-panel-only timeline.)
2. **Attempt reason source** — carry `replan_reason` on the **next attempt's `DAG_NODE_START`** payload. (No separate per-attempt review event.)
3. **Rendering engine** — **retain React Flow** (keep pan/zoom); port the visual language into custom nodes/edges rather than a pure CSS board.

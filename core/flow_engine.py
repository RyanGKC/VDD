"""
Drives the deterministic DAG flow and hands control to the supervisor
whenever a step raises an anomaly or at the end of the DAG execution.

  * The happy path has no LLM in the orchestration loop if the due-diligence runs have 
    no anomalies. Running agents in a predictable, testable, and parallel order.
  * LLM-based re-planning is only used at the end of a run to check for off-script issues.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from typing import TYPE_CHECKING, Callable, Awaitable

from core.models import (
    DDContext,
    IDEAL_FLOW,
    DAG_DEPENDENCIES,
    StepName,
    StepResult,
)

# Avoid circular imports but allow type hinting
if TYPE_CHECKING:
    from agents.base_agent import BaseResearchAgent
    from agents.supervisor_agent import SupervisorAgent

logger = logging.getLogger(__name__)

# Guardrail: cap how many times the supervisor may re-plan, so a pathological
# anomaly loop can never run forever (and run up an unbounded API bill).
MAX_REPLANS = 5

class FlowEngine:
    def __init__(
        self,
        agents: dict[StepName, "BaseResearchAgent"],
        supervisor: "SupervisorAgent",
        summary_agent=None,
    ) -> None:
        self._agents = agents
        self._supervisor = supervisor
        self._summary = summary_agent
        
        # Validation: Ensure we have an agent for every step in the Ideal Flow
        missing_agents = [step for step in IDEAL_FLOW if step not in self._agents]
        if missing_agents:
            raise ValueError(f"Missing registered agents for steps: {missing_agents}")

    async def _execute_dag(
        self, 
        plan: list[StepName], 
        ctx: DDContext, 
        step_execution_counts: dict[StepName, int],
        on_step_complete: Callable[[StepName, DDContext], Awaitable[None]] | None = None
    ) -> set[StepName]:
        pending = set(plan)
        running_tasks = {} # Map from asyncio.Task -> StepName
        completed_this_round = set()
        
        while pending or running_tasks:
            ready_to_run = []
            for step in list(pending):
                deps = DAG_DEPENDENCIES.get(step, [])
                # A step is ready if all its dependencies have been completed in ANY round
                # However, if a dependency is scheduled to be re-run in THIS round (pending or running), we MUST wait for it.
                unmet_deps = [
                    d for d in deps 
                    if (d in pending or d in running_tasks.values()) or 
                       (d not in ctx.results and d not in completed_this_round)
                ]
                if not unmet_deps:
                    ready_to_run.append(step)

            for step in ready_to_run:
                pending.remove(step)
                
                # Enforce MAX_STEP_RETRIES here
                MAX_STEP_RETRIES = 2
                if step_execution_counts.get(step, 0) > MAX_STEP_RETRIES:
                    ctx.log(f"GUARDRAIL: Dropping {step.value} to prevent infinite loop (max retries).")
                    completed_this_round.add(step)
                    continue

                step_execution_counts[step] = step_execution_counts.get(step, 0) + 1
                agent = self._agents[step]
                
                # Schedule task
                task = asyncio.create_task(agent.run(ctx))
                running_tasks[task] = step

            if not running_tasks:
                if pending:
                    ctx.log(f"DAG DEADLOCK: Unmet dependencies for {[s.value for s in pending]}")
                break

            # Wait for at least one task to complete
            try:
                done, _ = await asyncio.wait(running_tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
            except asyncio.CancelledError:
                for t in running_tasks.keys():
                    t.cancel()
                raise
            
            for task in done:
                step = running_tasks.pop(task)
                try:
                    result = task.result()
                    completed_this_round.add(step)
                    print(f"DEBUG _execute_dag: completed {step}, on_step_complete={on_step_complete}")
                    if on_step_complete:
                        await on_step_complete(step, ctx)
                except Exception as e:
                    ctx.log(f"DAG ERROR: {step.value} failed with {e}")
                    completed_this_round.add(step)

        return completed_this_round

    async def run(
        self, 
        ctx: DDContext,
        on_step_complete: Callable[[StepName, DDContext], Awaitable[None]] | None = None
    ) -> DDContext:
        """Execute the full due-diligence flow with DAG-based parallelism and batched review."""
        plan: list[StepName] = list(IDEAL_FLOW)
        replans = 0
        step_execution_counts: dict[StepName, int] = {}
        all_completed: set[StepName] = set()

        while plan:
            # 1. Execute the current plan as a DAG
            ctx.log(f"SYSTEM: Spawning DAG execution for {len(plan)} steps...")
            completed_this_round = await self._execute_dag(plan, ctx, step_execution_counts, on_step_complete)
            all_completed.update(completed_this_round)

            # 2. Batched Supervisor Review & Speculative Contradiction Detection
            ctx.log("SUPERVISOR batch reviewing all completed results...")
            
            import asyncio
            supervisor_task = self._supervisor.review(ctx=ctx, completed=all_completed)
            
            # Speculative contradiction detection: If no replan occurs, we keep the cleaned findings.
            if self._summary:
                all_findings = []
                from agents.summary_agent import _STEP_LABELS
                for step_name, r in ctx.results.items():
                    category_name = _STEP_LABELS.get(step_name, step_name.value) if hasattr(step_name, 'value') else step_name
                    for f in r.findings:
                        f.category = category_name
                        for s in f.sources:
                            title_lower = s.title.lower()
                            if not s.url or "registry" in title_lower or "database" in title_lower or "sec " in title_lower or "sanctions" in title_lower:
                                s.is_database = True
                        all_findings.append(f)
                        
                contradiction_task = self._summary._detect_contradictions(all_findings)
                (new_plan, is_anomaly), removal_indices = await asyncio.gather(supervisor_task, contradiction_task)
                
                # Store it in ctx so synthesise can skip the LLM call
                ctx._cached_contradiction_indices = removal_indices
                ctx._cached_all_findings = all_findings
            else:
                new_plan, is_anomaly = await supervisor_task

            if is_anomaly and new_plan:
                if replans >= MAX_REPLANS:
                    ctx.log(f"REPLAN LIMIT reached; ignoring supervisor anomaly to avoid loop.")
                    break
                else:
                    replans += 1
                    ctx.log(f"SUPERVISOR detected anomaly (replan #{replans})")
                    # Clear the speculative cache because we're getting more findings!
                    if hasattr(ctx, '_cached_contradiction_indices'):
                        del ctx._cached_contradiction_indices
                        del ctx._cached_all_findings
                        
                    uncompleted_original = [s for s in IDEAL_FLOW if s not in all_completed and s not in new_plan]
                    plan = new_plan + uncompleted_original
                    ctx.log(f"NEW PLAN: {[s.value for s in plan]}")
            else:
                break # All good, no replans needed

        # ── Post-run: flush pending background ingestion tasks ─────────────────
        # This is the single synchronization point. All agent nodes have completed;
        # now we wait for any still-running background ingestion tasks so that
        # documents fetched late in the run are guaranteed to be in the vector store
        # before the run is marked done.
        run_id = getattr(ctx, 'run_id', None)
        bg = getattr(ctx, 'background_tasks', None)
        sf = getattr(ctx, 'singleflight', None)

        if bg and run_id:
            pending = bg.pending_count(run_id)
            if pending > 0:
                ctx.log(f"SYSTEM: Flushing {pending} pending background ingestion task(s)...")
            await bg.await_all(run_id)
            bg.clear_run(run_id)

        if sf and run_id:
            sf.clear_run(run_id)

        return ctx
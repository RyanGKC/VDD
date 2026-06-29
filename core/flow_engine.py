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
    ) -> None:
        self._agents = agents
        self._supervisor = supervisor
        
        # Validation: Ensure we have an agent for every step in the Ideal Flow
        missing_agents = [step for step in IDEAL_FLOW if step not in self._agents]
        if missing_agents:
            raise ValueError(f"Missing registered agents for steps: {missing_agents}")

    async def _execute_dag(self, plan: list[StepName], ctx: DDContext, step_execution_counts: dict[StepName, int]) -> set[StepName]:
        pending = set(plan)
        running_tasks = {} # Map from asyncio.Task -> StepName
        completed_this_round = set()
        
        while pending or running_tasks:
            ready_to_run = []
            for step in list(pending):
                deps = DAG_DEPENDENCIES.get(step, [])
                # A step is ready if all its dependencies have been completed in ANY round
                unmet_deps = [d for d in deps if d not in ctx.results and d not in completed_this_round]
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
            done, _ = await asyncio.wait(running_tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
            
            for task in done:
                step = running_tasks.pop(task)
                try:
                    result = task.result()
                    completed_this_round.add(step)
                except Exception as e:
                    ctx.log(f"DAG ERROR: {step.value} failed with {e}")
                    completed_this_round.add(step)

        return completed_this_round

    async def run(self, ctx: DDContext) -> DDContext:
        """Execute the full due-diligence flow with DAG-based parallelism and batched review."""
        plan: list[StepName] = list(IDEAL_FLOW)
        replans = 0
        step_execution_counts: dict[StepName, int] = {}
        all_completed: set[StepName] = set()

        while plan:
            # 1. Execute the current plan as a DAG
            ctx.log(f"SYSTEM: Spawning DAG execution for {len(plan)} steps...")
            completed_this_round = await self._execute_dag(plan, ctx, step_execution_counts)
            all_completed.update(completed_this_round)

            # 2. Batched Supervisor Review
            ctx.log("SUPERVISOR batch reviewing all completed results...")
            new_plan, is_anomaly = await self._supervisor.review(
                ctx=ctx,
                completed=all_completed,
            )

            if is_anomaly and new_plan:
                if replans >= MAX_REPLANS:
                    ctx.log(f"REPLAN LIMIT reached; ignoring supervisor anomaly to avoid loop.")
                    break
                else:
                    replans += 1
                    ctx.log(f"SUPERVISOR detected anomaly (replan #{replans})")
                    plan = new_plan
                    ctx.log(f"NEW PLAN: {[s.value for s in plan]}")
            else:
                break # All good, no replans needed

        return ctx
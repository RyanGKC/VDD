"""
The supervisor is the only LLM-driven orchestration agent. 

It now acts as a Quality Control & Anomaly Detector. After every step,
it reviews the findings to decide if the pipeline should proceed or if an
anomaly occurred that requires adjusting parameters (like the company name)
and re-planning.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field

from typing import Any
from core.openai_client import OpenAIClient
from core.models import (
    DDContext,
    IDEAL_FLOW,
    StepName,
    StepResult,
)
from core.tools import perform_web_search
from core.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """
You are the supervisor of a vendor due-diligence pipeline. The ideal flow
runs these steps in order:
  shareholders -> kyb -> sanctions -> profile -> licenses -> finances ->
  resilience -> esg -> media

Your job is to review the aggregated results of all completed steps at once.
Look for contradictions, missing data, or discoveries that invalidate previous findings
(e.g., if a company wasn't found, maybe the name needs to be adjusted; if a 
hidden UBO was found, maybe we need to re-run KYB).

If you need to verify a fact online (e.g., "Did this company change its name?"), you will first have an opportunity to plan up to 3 web searches. You will then receive the results of those searches before making your final decision.

CRITICAL HEURISTICS FOR HANDLING "NOT FOUND" FAILURES:
* If a registry search fails, critically evaluate the parameters for obvious contradictions.
* Entity Suffixes: If the company name contains "Limited", "Ltd", or "Plc" but the country is "United States", it is almost certainly a UK company. Update the country to "United Kingdom". 
* Conversely, if it contains "LLC", "Inc", or "Corp" but the country is "United Kingdom", update it to "United States".
* Name Typos: If a name includes strange punctuation or suffixes that might break a search (e.g. "Subway Us Holdings, LLC"), try stripping them (e.g. "Subway") and re-running.
* LOOP PREVENTION: Review the Execution Log history! If you see that you already tried updating a parameter and the step failed again, DO NOT try adjusting parameters and re-queueing again. Accept the missing data, set 'is_anomaly' to false, and proceed.
* CRASHED STEPS: If you are informed that some steps have CRASHED (e.g. due to an API timeout), and you believe their data is necessary for the report, you MUST set is_anomaly to true and add them to steps_to_run to force a retry.

If you detect an anomaly or a reason to adjust the plan:
1. Set 'is_anomaly' to true.
2. Provide a rationale.
3. If any parameters (country, registration number, address, website, or tax ID) 
   need adjusting, output the corrected value in the corresponding 'updated_*' field. 
   The primary 'company_name' is immutable and CANNOT be changed. DO NOT attempt to change the target company to a subsidiary, UBO, or related party. If you discover a related entity (like a subsidiary) that requires investigation, add it to the 'new_enrichment' field.
4. Output the minimum set of steps to re-run due to this anomaly.

If everything looks normal, set 'is_anomaly' to false and return an empty list.

Rules:
  * Re-run a completed step ONLY if new information would materially change its result.
  * Do not drop steps that haven't run yet unless they are completely irrelevant.
  * Return ONLY step names from the known set, no duplicates beyond what is necessary.
  * CRITICAL ANTI-LOOP RULE: If you are revisiting a step that has already failed for a similar reason, do NOT schedule it again to prevent an infinite loop. Just document the ambiguity and move on.
"""

class _SearchQuery(BaseModel):
    query: str
    goal: str

class _ReviewPlan(BaseModel):
    research_plan: list[_SearchQuery] = []

class _ReviewDecision(BaseModel):
    is_anomaly: bool
    rationale: str
    updated_registration_number: str | None = None
    updated_country: str | None = None
    updated_address: str | None = None
    updated_website: str | None = None
    updated_tax_id: str | None = None
    new_enrichment: dict[str, str] | None = None
    steps_to_run: list[StepName]

class SupervisorAgent:
    def __init__(self, client: Any) -> None:
        self.openai = client
        self.gemini = client

    async def review(
        self,
        *,
        ctx: DDContext,
        completed: set[StepName],
        review_round: int = 1,
    ) -> tuple[list[StepName], bool]:
        
        # Calculate which steps actually completed successfully vs crashed
        successful_steps = set(ctx.results.keys())
        crashed_steps = completed - successful_steps
        
        prompt = (
            f"Vendor: {ctx.company_details.company_name}\n"
            f"\n--- FINDINGS FROM ALL COMPLETED STEPS ---\n"
        )
        if not ctx.results:
            prompt += " (No steps completed yet)\n"
        for step_name, past_result in ctx.results.items():
            prompt += f"Step: {step_name.value}\n"
            for f in past_result.findings:
                prompt += f"  - [{f.severity.value}] {f.summary}\n"
            
        if crashed_steps:
            prompt += f"\n--- CRASHED STEPS ---\n"
            prompt += "The following steps crashed due to an unexpected error and produced no findings:\n"
            for step in crashed_steps:
                prompt += f"  - {step.value}\n"
            prompt += "If you believe their data is necessary, you MUST set is_anomaly to true and add them to steps_to_run to force a retry. If the execution log says it has permanently failed, DO NOT retry it.\n"
            
        prompt += (
            f"\nSteps already completed (including crashed): {[s.value for s in completed]}\n"
            f"Current enrichment context: {ctx.enrichment}\n\n"
            f"Recent Execution Log (for loop prevention):\n"
        )
        for log_entry in ctx.execution_log[-15:]:
            prompt += f"  {log_entry}\n"
            
        from core.dependencies import neo4j
        risky_neighbors = await neo4j.get_risky_neighbors(ctx.company_details.company_name, max_hops=2)
        
        if risky_neighbors:
            prompt += "\n--- GRAPH RAG: RISKY NETWORK CONNECTIONS (N-HOP) ---\n"
            for n in risky_neighbors:
                prompt += f"  - Entity: {n['name']} (Risk: {n['risk']})\n"
            prompt += "  (Consider this network risk in your anomaly assessment.)\n"
            
        base_prompt = (
            "\nReview the findings. If there is an anomaly or missing data that "
            "can be fixed by changing the query or re-running steps, do so. "
            "Otherwise, set is_anomaly to false."
        )

        max_searches = 3
        
        # --- Phase 1: Ask the Supervisor to plan verification searches ---
        plan_prompt = (
            prompt + base_prompt +
            f"\n\nBefore making your final decision, you may plan up to {max_searches} web searches to verify facts. "
            "Think strategically: what would you need to look up to confirm or deny a suspected anomaly?\n"
            "Output a research_plan: a list of objects, each with a 'query' and a 'goal'. "
            "If no verification is needed, return an empty research_plan."
        )
        
        from rag.rate_limiter import run_foreground_generation
        plan_result = await run_foreground_generation(
            lambda: self.gemini.generate_structured(
                system_instruction=SYSTEM_INSTRUCTION,
                prompt=plan_prompt,
                schema=_ReviewPlan,
            )
        )
        
        queries = plan_result.research_plan[:max_searches] if plan_result.research_plan else []
        
        # --- Phase 2: Execute all planned searches ---
        search_context = ""
        if queries:
            print(f"[SUPERVISOR] Research Plan ({len(queries)} searches):")
            ctx.audit(f"[SUPERVISOR] Planned {len(queries)} verification searches.")
            for i, q in enumerate(queries):
                print(f"  {i+1}. [{q.goal}] → '{q.query}'")
                ctx.log(f"WEB SEARCH step=supervisor query='{q.query}' goal='{q.goal}'")

            async def _run_supervisor_search(i: int, q):
                result_str = await perform_web_search(ctx, q.query)
                formatted_data = result_str
                try:
                    import json
                    parsed = json.loads(result_str)
                    formatted_data = json.dumps(parsed, indent=2)
                except Exception:
                    pass
                ctx.audit(f"[SUPERVISOR] Verification Search {i+1} [{q.query}]:\n{formatted_data}")
                return f"Search {i+1} — Goal: {q.goal}\nQuery: {q.query}\nResults: {result_str}"

            search_results = await asyncio.gather(*[_run_supervisor_search(i, q) for i, q in enumerate(queries)])
            search_context = "\n\n--- WEB RESEARCH RESULTS ---\n" + "\n\n".join(search_results)
        
        # --- Phase 3: Final decision with all context ---
        final_prompt = prompt + base_prompt + search_context
        if search_context:
            final_prompt += "\n\nUsing the research results above, make your final decision."
        
        from rag.rate_limiter import run_foreground_generation
        decision = await run_foreground_generation(
            lambda: self.gemini.generate_structured(
                system_instruction=SYSTEM_INSTRUCTION,
                prompt=final_prompt,
                schema=_ReviewDecision,
            )
        )

        ctx.log(f"SUPERVISOR rationale: {decision.rationale}")
        ctx.audit(f"[SUPERVISOR] Decision Rationale:\n{decision.rationale}")

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

        if not decision.is_anomaly:
            return [], False
            
        if decision.updated_registration_number:
            ctx.log(f"SUPERVISOR updated registration number from {ctx.company_details.registration_number} to {decision.updated_registration_number}")
            ctx.company_details.registration_number = decision.updated_registration_number
            
        if decision.updated_country:
            ctx.log(f"SUPERVISOR updated country from {ctx.company_details.country} to {decision.updated_country}")
            ctx.company_details.country = decision.updated_country
            
        if decision.updated_address:
            ctx.log(f"SUPERVISOR updated address to {decision.updated_address}")
            ctx.company_details.address = decision.updated_address
            
        if decision.updated_website:
            ctx.log(f"SUPERVISOR updated website to {decision.updated_website}")
            ctx.company_details.website = decision.updated_website
            
        if decision.updated_tax_id:
            ctx.log(f"SUPERVISOR updated tax ID to {decision.updated_tax_id}")
            ctx.company_details.tax_id = decision.updated_tax_id
            
        if decision.new_enrichment:
            ctx.enrichment.update(decision.new_enrichment)

        # Validation guardrails on the LLM's plan
        plan: list[StepName] = []
        for s in decision.steps_to_run:
            if s in IDEAL_FLOW and s not in plan:
                plan.append(s)

        if not hasattr(ctx, '_replan_rationale'):
            ctx._replan_rationale = {}
        for s in plan:
            ctx._replan_rationale[s] = decision.rationale

        if getattr(ctx, 'checkpoint_db', None) and ctx.run_id:
            import json
            await ctx.checkpoint_db.save_intervention(
                run_id=ctx.run_id,
                replan_json=json.dumps([s.value for s in plan]),
                context_json=json.dumps({
                    "updated_country": decision.updated_country,
                    "updated_registration_number": decision.updated_registration_number,
                })
            )

        return plan, True
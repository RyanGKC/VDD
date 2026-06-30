# Base class for all research agents

from __future__ import annotations

import abc
import logging
import json

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue, Event
from a2a.types import AgentCard, AgentSkill, Message, Part

from core.models import DDContext, StepName, StepResult
from core.tools import perform_web_search
from pydantic import BaseModel
from typing import Type, TypeVar, Any

TModel = TypeVar("TModel", bound=BaseModel)

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

class BaseResearchAgent(AgentExecutor, abc.ABC):
    # All research agents share this contract.
    # By subclassing A2A's AgentExecutor, every agent can be served as an
    # independent A2A endpoint AND invoked in-process by the flow engine.

    #: Which step this agent owns. Set by each subclass.
    step: StepName

    def __init__(self, client: Any) -> None:
        self.openai = client
        self.gemini = client

    async def generate_with_web_search(self, ctx: DDContext, system_instruction: str, base_prompt: str, schema: Type[TModel]) -> TModel:
        step_val = self.step.value if hasattr(self, 'step') else 'AGENT'
        max_searches = 3
        
        # --- Phase 1: Ask the LLM to plan its research strategy ---
        plan_prompt = (
            base_prompt +
            f"\n\nBefore providing your final analysis, you may plan up to {max_searches} web searches to supplement the data above. "
            "Think strategically: what specific information gaps exist? What queries would best fill them?\n"
            "Output a research_plan: a list of objects, each with a 'query' (the search string) and a 'goal' (why this search is needed). "
            "If the data above is already sufficient, return an empty research_plan and provide your final findings directly."
        )
        
        plan_result = await self.gemini.generate_structured(
            system_instruction=system_instruction,
            prompt=plan_prompt,
            schema=_PlanAndAnalysis.with_findings_schema(schema)
        )
        
        queries = plan_result.research_plan[:max_searches] if plan_result.research_plan else []
        
        # If no searches needed, extract the final analysis directly
        if not queries:
            print(f"[{step_val.upper()}] No web searches needed — data sufficient.")
            return await self.gemini.generate_structured(
                system_instruction=system_instruction,
                prompt=base_prompt,
                schema=schema
            )
        
        # --- Phase 2: Execute all planned searches ---
        print(f"[{step_val.upper()}] Research Plan ({len(queries)} searches):")
        search_results = []
        for i, q in enumerate(queries):
            query_str = q.query
            goal_str = q.goal
            print(f"  {i+1}. [{goal_str}] → '{query_str}'")
            ctx.log(f"WEB SEARCH step={step_val} query='{query_str}' goal='{goal_str}'")
            
            result_str = await perform_web_search(ctx, query_str)
            search_results.append(f"Search {i+1} — Goal: {goal_str}\nQuery: {query_str}\nResults: {result_str}")
        
        # --- Phase 3: Final analysis with all search results ---
        final_prompt = (
            base_prompt +
            "\n\n--- WEB RESEARCH RESULTS ---\n" +
            "\n\n".join(search_results) +
            "\n\nUsing ALL of the data above (both the original data and the web research results), provide your final analysis."
        )
        
        analysis = await self.gemini.generate_structured(
            system_instruction=system_instruction,
            prompt=final_prompt,
            schema=schema
        )
        
        return analysis

        return analysis

    # A2A discovery: advertise what this agent can do.
    @property
    def agent_card(self) -> AgentCard:
        # The A2A 'business card' that lets other agents discover this one.
        return AgentCard(
            name=f"{self.step.value}_research_agent",
            description=self.__doc__ or f"Researches {self.step.value}",
            version="1.0.0",
            skills=[
                AgentSkill(
                    id=f"research_{self.step.value}",
                    name=f"Research {self.step.value}",
                    description=f"Performs {self.step.value} due diligence.",
                    tags=["due-diligence", self.step.value],
                )
            ],
        )

    # Core work — implemented by each subclass.
    @abc.abstractmethod
    async def research(self, ctx: DDContext) -> StepResult:
        """
        Perform the actual async research and return a StepResult.

        Implementations should:
          * read prior results from `ctx.results` when relevant,
          * attach Sources to every Finding,
          * set `result.anomaly` if they discover something that invalidates
            an earlier step.
        """
        raise NotImplementedError

    # Public entry point used by the flow engine. Wraps research() with
    # uniform logging and error handling.
    async def run(self, ctx: DDContext) -> StepResult:
        print(f"\n--- Running {self.step.value.upper()} Agent ---")
        ctx.log(f"START step={self.step.value}")
        try:
            # Await the async research logic
            result = await self.research(ctx)
        except Exception as exc:  # noqa: BLE001 - we deliberately catch all
            logger.exception("Agent %s failed", self.step.value)
            ctx.log(f"ERROR step={self.step.value} err={exc}")
            print(f"[{self.step.value.upper()}] Agent failed with error: {exc}")
            # Return an empty-but-valid result so the flow can continue
            return StepResult(step=self.step)

        # Mutate the context memory locally
        ctx.results[self.step] = result
        
        if result.anomaly:
            ctx.log(
                f"ANOMALY step={self.step.value} "
                f"severity={result.anomaly.severity.value} "
                f"reason={result.anomaly.reason}"
            )
            print(f"[{self.step.value.upper()}] ANOMALY RAISED: {result.anomaly.reason}")
            
        ctx.log(f"DONE step={self.step.value} findings={len(result.findings)}")
        print(f"[{self.step.value.upper()}] Completed with {len(result.findings)} findings:")
        if result.rationale:
            print(f"  > Rationale: {result.rationale}")
            ctx.audit(f"[{self.step.value.upper()}] Rationale:\n{result.rationale}")
        if result.raw_data:
            snippet = result.raw_data[:300].replace('\n', ' ')
            print(f"  > Raw Data: {snippet}...")
            
            # Format raw data for readability in the audit log
            formatted_data = result.raw_data
            try:
                import json
                parsed = json.loads(result.raw_data)
                formatted_data = json.dumps(parsed, indent=2)
            except Exception:
                pass
                
            ctx.audit(f"[{self.step.value.upper()}] Raw Data:\n{formatted_data}")
        for f in result.findings:
            print(f"  - [{f.severity.value.upper()}] {f.summary}")
            
        return result

    # A2A protocol method (for serving the agent remotely). 
    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        # Receives A2A request, parses context, runs, and returns StepResult JSON.
        # Parse the incoming context from the orchestrator
        input_data = context.get_user_input()
        ctx = DDContext.model_validate_json(input_data)
        
        # Execute the agent's core loop
        result = await self.run(ctx)
        
        # Enqueue the structured response back to the A2A network
        msg = Message(parts=[Part(text=result.model_dump_json())])
        await event_queue.enqueue_event(Event(message=msg))

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise NotImplementedError("Cancellation not supported.")


class _SearchQuery(BaseModel):
    query: str
    goal: str

class _PlanAndAnalysis(BaseModel):
    research_plan: list[_SearchQuery] = []
    
    @classmethod
    def with_findings_schema(cls, findings_schema: Type[TModel]) -> Type["_PlanAndAnalysis"]:
        """Returns a schema that only asks for the research plan (no findings yet)."""
        return cls
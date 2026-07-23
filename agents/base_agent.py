# Base class for all research agents

from __future__ import annotations

import abc
import logging
import json
import asyncio

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue, Event
from a2a.types import AgentCard, AgentSkill, Message, Part

from core.models import DDContext, StepName, StepResult
from core.tools import perform_web_search
from pydantic import BaseModel
from typing import Type, TypeVar, Any

TModel = TypeVar("TModel", bound=BaseModel)

logger = logging.getLogger(__name__)

class _SearchQuery(BaseModel):
    query: str
    goal: str

class _PlanAndAnalysis(BaseModel):
    research_plan: list[_SearchQuery] = []
    
    @classmethod
    def with_findings_schema(cls, findings_schema: Type[TModel]) -> Type["_PlanAndAnalysis"]:
        """Returns a schema that only asks for the research plan (no findings yet)."""
        return cls

class BaseResearchAgent(AgentExecutor, abc.ABC):
    # All research agents share this contract.
    # By subclassing A2A's AgentExecutor, every agent can be served as an
    # independent A2A endpoint AND invoked in-process by the flow engine.

    #: Which step this agent owns. Set by each subclass.
    step: StepName

    def __init__(self, client: Any) -> None:
        self.openai = client
        self.gemini = client

    @property
    def default_queries(self) -> list[str]:
        """Override to provide deterministic queries when cache is cold."""
        return []

    async def generate_with_web_search(self, ctx: DDContext, system_instruction: str, base_prompt: str, schema: Type[TModel]) -> TModel:
        step_val = self.step.value if hasattr(self, 'step') else 'AGENT'
        max_searches = getattr(ctx, 'search_budget', 3)
        
        # Check cache early to bypass LLM planning if cold
        cache_hit = False
        cache_gate = getattr(ctx, 'cache_gate', None)
        if cache_gate and getattr(ctx, 'enable_rag', True):
            # Just do a fast check, we'll hit it again in Phase 2 but it's cheap
            cache_res = await cache_gate.check(
                entity_name=ctx.company_details.company_name,
                entity_type="company",
                document_kind=step_val,
                goal_str="",  # Fast check, no goal yet
                run_id=ctx.run_id,
            )
            if cache_res.status == "HIT":
                cache_hit = True

        queries = []
        if not cache_hit and self.default_queries:
            default_qs = self.default_queries[:max_searches]
            ctx.log(f"[{step_val.upper()}] Cache MISS: Skipping LLM planning, using {len(default_qs)} default queries (budget: {max_searches}).")
            print(f"[{step_val.upper()}] Cache MISS: Skipping LLM planning, using {len(default_qs)} default queries (budget: {max_searches}).")
            queries = [
                _SearchQuery(
                    query=q.format(company=ctx.company_details.company_name), 
                    goal="Default cold-start query"
                ) for q in default_qs
            ]
        else:
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
            
            if getattr(ctx, 'audit_logger', None):
                await ctx.audit_logger.log_generation(
                    run_id=ctx.run_id,
                    agent_id=step_val,
                    claim=f"Generated Research Plan: {[q.query for q in plan_result.research_plan]}",
                    supporting_chunk_ids=[],
                    model_version=getattr(self.gemini, '_model', 'unknown'),
                    parent_event_id=ctx.audit_agent_event_ids.get(step_val, ctx.audit_pipeline_event_id),
                    entity_name=ctx.company_details.company_name,
                    entity_role=ctx.entity_role,
                )
                
            queries = plan_result.research_plan[:max_searches] if plan_result.research_plan else []
        
        # If no searches needed, extract the final analysis directly
        if not queries:
            print(f"[{step_val.upper()}] No web searches needed — data sufficient.")
            analysis = await self.gemini.generate_structured(
                system_instruction=system_instruction,
                prompt=base_prompt,
                schema=schema
            )
            return analysis, {}
        
        # --- Phase 2: Execute all planned searches with async RAG orchestration ---
        print(f"[{step_val.upper()}] Research Plan ({len(queries)} searches):")
        
        url_map = {}
        
        async def _execute_single_search(i: int, q: Any) -> str:
            query_str = q.query
            goal_str = q.goal
            ctx.log(f"[{step_val.upper()}] Executing search {i+1}/{len(queries)}: '{query_str}'")
            result_str: str | None = None

            replan_rationale = getattr(ctx, '_replan_rationale', {}).get(step_val)
            if replan_rationale:
                goal_str += f"\n\nSUPERVISOR FEEDBACK FROM PREVIOUS FAILED ATTEMPT:\n{replan_rationale}\nAvoid the mistakes mentioned above."
                
            is_cache_hit = False
            cache_gate = getattr(ctx, 'cache_gate', None)
            if cache_gate and getattr(ctx, 'enable_rag', True) and not replan_rationale:
                cache_res = await cache_gate.check(
                    entity_name=ctx.company_details.company_name,
                    entity_type="company",
                    document_kind=step_val,
                    goal_str=goal_str,
                    run_id=ctx.run_id,
                )
                if cache_res.status == "HIT" and cache_res.chunks:
                    result_str = "\n\n".join(cache_res.chunks)
                    is_cache_hit = True
                    ctx.log(f"RAG CACHE HIT step={step_val} — skipped external API call")

            # ── Step B: MISS path — singleflight-coordinated fetch ────────
            is_sf_follower = False
            if result_str is None:
                sf = getattr(ctx, 'singleflight', None)
                run_id = getattr(ctx, 'run_id', None)

                if sf and run_id:
                    import hashlib
                    fp_key = hashlib.sha256(f"{query_str}".encode()).hexdigest()
                    outcome = await sf.acquire_or_wait(fp_key, run_id)

                    if outcome.role == "follower" and outcome.data is not None:
                        result_str = outcome.data
                        is_sf_follower = True
                        ctx.log(f"SingleFlight FOLLOWER step={step_val} — reused leader's fetch")
                    else:
                        try:
                            result_str = await perform_web_search(ctx, query_str)
                            sf.resolve(fp_key, run_id, result_str)
                        except BaseException as fetch_exc:
                            sf.fail(fp_key, run_id, fetch_exc)
                            raise
                else:
                    result_str = await perform_web_search(ctx, query_str)
            # ── Step B.5: Map URLs to source_ids and extract sources ──
            import json
            import hashlib
            current_search_urls = []
            
            # If it's a cache hit, we already have sources from cache_res
            if is_cache_hit and cache_res.sources:
                current_search_urls = cache_res.sources
            else:
                try:
                    data = json.loads(result_str)
                    if "results" in data:
                        for res in data["results"]:
                            url = res.get("source_url") or res.get("url")
                            if url:
                                sid = f"src_{hashlib.md5(url.encode()).hexdigest()[:8]}"
                                url_map[sid] = url
                                current_search_urls.append(url)
                                res["source_id"] = sid
                                res.pop("source_url", None)
                                res.pop("url", None)
                        result_str = json.dumps(data, indent=2)
                except Exception:
                    pass

            # ── Step B.6: Log RETRIEVAL event ──────────────
            al = getattr(ctx, 'audit_logger', None)
            start_event_id = ctx.audit_agent_event_ids.get(step_val, ctx.audit_pipeline_event_id)
            if al and ctx.run_id and result_str:
                evidence = [{
                    "id": chunk_id,
                    "text": result_str[:12000],
                    "metadata": {"query": query_str, "source_domains": current_search_urls, "kind": "web_search"},
                } for chunk_id in [hashlib.md5(query_str.encode()).hexdigest()]]
                await al.log_retrieval(
                    run_id=ctx.run_id,
                    agent_id="cache_gate" if is_cache_hit else step_val,
                    query=goal_str if is_cache_hit else query_str,
                    chunk_ids=[hashlib.md5(query_str.encode()).hexdigest()],
                    source_domains=current_search_urls,
                    relevance_scores=[],
                    parent_event_id=start_event_id,
                    entity_name=ctx.company_details.company_name,
                    entity_role=ctx.entity_role,
                    evidence=evidence,
                )

            # ── Step C: Fire-and-forget background ingestion ──────────────
            bg = getattr(ctx, 'background_tasks', None)
            ingestion_pipeline = getattr(ctx, 'ingestion_pipeline', None)
            run_id = getattr(ctx, 'run_id', None)

            if bg and ingestion_pipeline and result_str and run_id and getattr(ctx, 'enable_rag', True) and not is_sf_follower and not is_cache_hit:
                bg.schedule(
                    ingestion_pipeline.ingest_document(
                        text=result_str, source_url=query_str, source_type=step_val, run_id=run_id,
                    ),
                    run_id,
                )

            # ── Step D: Try retrieval engine for a focused context window ─
            retrieval_engine = getattr(ctx, 'retrieval_engine', None)
            if retrieval_engine and run_id and getattr(ctx, 'enable_rag', True):
                try:
                    retrieval_res = await retrieval_engine.retrieve(
                        query=goal_str, entity_name=ctx.company_details.company_name, entity_type="company",
                        collection_name="run_documents", run_id=run_id, top_k=4,
                    )
                    distilled = retrieval_res.primary
                    if distilled:
                        retrieval_text = "...\n".join(distilled)
                        result_str = f"Raw Data:\n{result_str}\n\nRetrieved Context:\n{retrieval_text}"
                        ctx.log(f"RAG DISTILLATION step={step_val} returned targeted chunks")
                        
                        if getattr(ctx, 'audit_logger', None):
                            ctx.current_chunk_ids = getattr(ctx, 'current_chunk_ids', []) + retrieval_res.primary_ids
                            await ctx.audit_logger.log_retrieval(
                                run_id=ctx.run_id,
                                agent_id=f"{step_val}_rag",
                                query=goal_str,
                                chunk_ids=retrieval_res.primary_ids,
                                source_domains=retrieval_res.primary_sources,
                                relevance_scores=[1.0] * len(distilled),
                                parent_event_id=ctx.audit_agent_event_ids.get(step_val, ctx.audit_pipeline_event_id),
                                entity_name=ctx.company_details.company_name,
                                entity_role=ctx.entity_role,
                                evidence=[{"id": cid, "text": c,
                                           "metadata": {"source": s, "kind": "rag"}}
                                          for c, s, cid in zip(distilled, retrieval_res.primary_sources, retrieval_res.primary_ids)],
                            )
                except Exception as rag_exc:
                    ctx.log(f"RAG DISTILLATION step={step_val} failed (non-blocking): {rag_exc}")

            return f"Search {i+1} — Goal: {goal_str}\nQuery: {query_str}\nResults: {result_str}"

        search_results = await asyncio.gather(*[_execute_single_search(i, q) for i, q in enumerate(queries)])
        
        # --- Phase 3: Final analysis with all search results ---
        final_prompt = (
            base_prompt +
            "\n\n--- WEB RESEARCH RESULTS ---\n" +
            "\n\n".join(search_results) +
            "\n\nUsing ALL of the data above (both the original data and the web research results), provide your final analysis."
        )
        from rag.rate_limiter import run_foreground_generation
        analysis = await run_foreground_generation(
            lambda: self.gemini.generate_structured(
                system_instruction=system_instruction,
                prompt=final_prompt,
                schema=schema
            )
        )
        
        return analysis, url_map

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
        if hasattr(ctx, 'log_event'):
            ctx.log_event(ctx.company_details.company_name, self.step.value, "running")
            
        al = getattr(ctx, 'audit_logger', None)
        start_event_id = None
        if al and ctx.run_id:
            from core.audit_logger import EventType
            # Link this agent's start event to the pipeline root (PIPELINE_START)
            # so the audit graph traversal can reach it from the root node.
            pipeline_start_event_id = ctx.audit_pipeline_event_id
            start_event_id = await al.log_dag_node(
                run_id=ctx.run_id,
                agent_id=self.step.value,
                event_type=EventType.DAG_NODE_START,
                parent_event_id=pipeline_start_event_id,
                entity_name=ctx.company_details.company_name,
                entity_role=ctx.entity_role,
            )
            ctx.audit_agent_event_ids[self.step.value] = start_event_id
            
        try:
            # Await the async research logic
            result = await self.research(ctx)
        except Exception as exc:  # noqa: BLE001 - we deliberately catch all
            logger.exception("Agent %s failed", self.step.value)
            ctx.log(f"ERROR step={self.step.value} err={exc}")
            if hasattr(ctx, 'log_event'):
                ctx.log_event(ctx.company_details.company_name, self.step.value, "error")
            print(f"[{self.step.value.upper()}] Agent failed with error: {exc}")
            if al and ctx.run_id:
                from core.audit_logger import EventType
                await al.log_dag_node(
                    run_id=ctx.run_id, agent_id=self.step.value, event_type=EventType.DAG_NODE_END,
                    parent_event_id=start_event_id, entity_name=ctx.company_details.company_name,
                    entity_role=ctx.entity_role, status="failed", anomaly=str(exc),
                )
            raise exc

        # Mutate the context memory locally
        ctx.results[self.step] = result
        
        # --- CHECKPOINT WRITE ---
        # Persist the completed StepResult to the checkpoint DB immediately.
        # This is the cheapest write in the pipeline and happens exactly once per LLM call.
        if getattr(ctx, 'checkpoint_db', None) and ctx.run_id:
            await ctx.checkpoint_db.save_step_result(
                run_id=ctx.run_id,
                entity_name=ctx.company_details.company_name,
                step_name=self.step.value,
                result_json=result.model_dump_json()
            )
        
        if result.anomaly:
            ctx.log(
                f"ANOMALY step={self.step.value} "
                f"severity={result.anomaly.severity.value} "
                f"reason={result.anomaly.reason}"
            )
            print(f"[{self.step.value.upper()}] ANOMALY RAISED: {result.anomaly.reason}")
            
        ctx.log(f"DONE step={self.step.value} findings={len(result.findings)}")
        if hasattr(ctx, 'log_event'):
            ctx.log_event(ctx.company_details.company_name, self.step.value, "completed")
        print(f"[{self.step.value.upper()}] Completed with {len(result.findings)} findings:")
        if result.rationale:
            print(f"  > Rationale: {result.rationale}")
            ctx.audit(f"[{self.step.value.upper()}] Rationale:\n{result.rationale}")
            
            if al and ctx.run_id:
                from core.audit_logger import EventType
                gen_event_id = await al.log_generation(
                    run_id=ctx.run_id,
                    agent_id=self.step.value,
                    claim=result.rationale,
                    supporting_chunk_ids=getattr(ctx, 'current_chunk_ids', []),
                    model_version=getattr(self.gemini, '_model', 'unknown'),
                    prompt_version=None,
                    parent_event_id=start_event_id,
                    entity_name=ctx.company_details.company_name,
                    entity_role=ctx.entity_role,
                )
                
                for f in result.findings:
                    if f.severity.value != "info":
                        await al.log_risk_flag(
                            run_id=ctx.run_id,
                            agent_id=self.step.value,
                            risk_type=f.category or f.severity.value,
                            severity=f.severity.value,
                            detail=f.summary,
                            confidence={"low":0.4,"medium":0.6,"high":0.8,"critical":0.95}.get(f.severity.value, 0.5),
                            parent_event_id=gen_event_id,
                            entity_name=ctx.company_details.company_name,
                            entity_role=ctx.entity_role,
                        )
                if result.anomaly:
                    await al.log_risk_flag(
                        run_id=ctx.run_id,
                        agent_id=self.step.value,
                        risk_type="anomaly",
                        detail=result.anomaly.reason,
                        confidence=0.9,
                        parent_event_id=gen_event_id,
                        entity_name=ctx.company_details.company_name,
                        entity_role=ctx.entity_role,
                    )

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
                
            if len(formatted_data) > 1000:
                formatted_data = f"[REDACTED: {len(formatted_data)} bytes of raw data]"
                
            ctx.audit(f"[{self.step.value.upper()}] Raw Data:\n{formatted_data}")
        for f in result.findings:
            print(f"  - [{f.severity.value.upper()}] {f.summary}")
            
        if al and ctx.run_id:
            from core.audit_logger import EventType
            await al.log_dag_node(
                run_id=ctx.run_id,
                agent_id=self.step.value,
                event_type=EventType.DAG_NODE_END,
                findings_count=len(result.findings),
                anomaly=result.anomaly.reason if result.anomaly else None,
                parent_event_id=start_event_id,
                entity_name=ctx.company_details.company_name,
                entity_role=ctx.entity_role,
            )
            
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

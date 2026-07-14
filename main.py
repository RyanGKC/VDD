"""
Builds the agent registry, the supervisor, and the flow engine, 
runs the pipeline, then asks the summary agent to synthesise the
final report.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging

from agents.esg_agent import ESGAgent
from agents.finances_agent import FinancesAgent
from agents.kyb_agent import KYBAgent
from agents.licenses_agent import LicensesAgent
from agents.media_agent import MediaAgent
from agents.profile_agent import ProfileAgent
from agents.resilience_agent import ResilienceAgent
from agents.sanctions_agent import SanctionsAgent
from agents.shareholders_agent import ShareholdersAgent
from agents.summary_agent import SummaryAgent
from agents.supervisor_agent import SupervisorAgent
from core.flow_engine import FlowEngine
from core.openai_client import OpenAIClient
from core.gemini_client import GeminiClient
from core.models import CompanyDetails, DDContext, DDReport, StepName, Severity
import os
from core.tools import fetch_corporate_registry
from core.dependencies import neo4j
from core.document_store import DocumentStore
from typing import Any

logging.basicConfig(level=logging.INFO)


def build_engine(client: Any) -> tuple[FlowEngine, SummaryAgent]:
    # Register one agent instance per step. The keys must match StepName so
    # the flow engine can look agents up by step.
    agents = {
        StepName.SHAREHOLDERS: ShareholdersAgent(client),
        StepName.KYB: KYBAgent(client),
        StepName.SANCTIONS: SanctionsAgent(client),
        StepName.PROFILE: ProfileAgent(client),
        StepName.LICENSES: LicensesAgent(client),
        StepName.FINANCES: FinancesAgent(client),
        StepName.RESILIENCE: ResilienceAgent(client),
        StepName.ESG: ESGAgent(client),
        StepName.MEDIA: MediaAgent(client),
    }
    supervisor = SupervisorAgent(client)
    summary = SummaryAgent(client)
    engine = FlowEngine(agents=agents, supervisor=supervisor, summary_agent=summary)
    return engine, summary


async def run_dd_with_ctx(ctx: DDContext) -> DDReport:
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    if provider == "gemini":
        client = GeminiClient(use_cache=ctx.use_mock)
    else:
        client = OpenAIClient(use_cache=ctx.use_mock)
        
    if getattr(ctx, 'checkpoint_db', None) and ctx.run_id:
        await ctx.checkpoint_db.mark_in_progress(ctx.run_id, ctx.company_details.company_name)
        # Hydrate completed steps
        completed_steps = await ctx.checkpoint_db.get_completed_steps(ctx.run_id, ctx.company_details.company_name)
        from core.models import StepResult
        for step_name, result_json in completed_steps.items():
            ctx.results[StepName(step_name)] = StepResult.model_validate_json(result_json)

    try:
        engine, summary_agent = build_engine(client)
        await neo4j.save_company_node(ctx.company_details.company_name, "PENDING")

        async def handle_step_complete(step: StepName, current_ctx: DDContext):

            if step == StepName.SHAREHOLDERS and current_ctx.enable_parent_company:
                parent_name = current_ctx.results[StepName.SHAREHOLDERS].structured_data.get("parent_company")
                if parent_name:
                    async with current_ctx.visited_lock:
                        # Semantic Graph Deduplication
                        similar_entity = await neo4j.find_similar_company(parent_name)
                        canonical_parent = similar_entity if similar_entity else parent_name
                        
                        is_duplicate = canonical_parent.lower() in current_ctx.visited_companies
                        if not is_duplicate:
                            current_ctx.visited_companies.add(canonical_parent.lower())
                            
                    await neo4j.save_ownership_edge(canonical_parent, current_ctx.company_details.company_name)
                    
                    if not is_duplicate:
                        if getattr(current_ctx, 'checkpoint_db', None) and current_ctx.run_id:
                            await current_ctx.checkpoint_db.enqueue_entity(
                                run_id=current_ctx.run_id,
                                entity_name=canonical_parent,
                                depth=1,
                                parent=current_ctx.company_details.company_name,
                                role='parent'
                            )
                        parent_ctx = DDContext(
                            company_details=CompanyDetails(company_name=canonical_parent),
                            use_mock=current_ctx.use_mock,
                            tiers_to_search=current_ctx.tiers_to_search if current_ctx.enable_parent_supply_chain else 1,
                            max_suppliers_per_node=current_ctx.max_suppliers_per_node,
                            enable_parent_company=False,
                            enable_parent_supply_chain=current_ctx.enable_parent_supply_chain,
                            entity_role='parent',
                            parent_entity=current_ctx.company_details.company_name,
                            run_id=current_ctx.run_id,
                            retrieval_engine=current_ctx.retrieval_engine,
                            ingestion_pipeline=current_ctx.ingestion_pipeline,
                            cache_gate=current_ctx.cache_gate,
                            singleflight=current_ctx.singleflight,
                            background_tasks=current_ctx.background_tasks,
                        )
                        # Assign by reference AFTER construction to bypass Pydantic's deep copy
                        parent_ctx.execution_log = current_ctx.execution_log
                        parent_ctx.detailed_audit_log = current_ctx.detailed_audit_log
                        parent_ctx.visited_companies = current_ctx.visited_companies
                        parent_ctx.visited_lock = current_ctx.visited_lock
                        parent_ctx.screened_entities = current_ctx.screened_entities
                        parent_ctx.screened_entities_lock = current_ctx.screened_entities_lock
                        current_ctx.log(f"SYSTEM: Spawning sub-pipeline for parent company: {parent_name}")
                        current_ctx.parent_task = asyncio.create_task(run_dd_with_ctx(parent_ctx))
                    else:
                        current_ctx.log(f"SYSTEM: Parent {canonical_parent} already visited. Linking edge only.")
                        stub = DDReport(
                            vendor_name=canonical_parent, overall_risk=Severity.INFO,
                            strengths=[], red_flags=[], recommendations=[], sources=[],
                            executive_summary="Duplicate node (already researched elsewhere in graph)."
                        )
                        async def return_stub_parent(s=stub): return s
                        current_ctx.parent_task = asyncio.create_task(return_stub_parent())

            if step == StepName.RESILIENCE and current_ctx.tiers_to_search > 1:
                suppliers = current_ctx.results[StepName.RESILIENCE].structured_data.get("suppliers", [])
                suppliers = suppliers[:current_ctx.max_suppliers_per_node]
                
                for supplier_name in suppliers:
                    async with current_ctx.visited_lock:
                        # Semantic Graph Deduplication
                        similar_entity = await neo4j.find_similar_company(supplier_name)
                        canonical_supplier = similar_entity if similar_entity else supplier_name
                        
                        is_duplicate = canonical_supplier.lower() in current_ctx.visited_companies
                        if not is_duplicate:
                            current_ctx.visited_companies.add(canonical_supplier.lower())
                    
                    await neo4j.save_supply_edge(canonical_supplier, current_ctx.company_details.company_name)
                    
                    if not is_duplicate:
                        if getattr(current_ctx, 'checkpoint_db', None) and current_ctx.run_id:
                            await current_ctx.checkpoint_db.enqueue_entity(
                                run_id=current_ctx.run_id,
                                entity_name=canonical_supplier,
                                depth=current_ctx.tiers_to_search,
                                parent=current_ctx.company_details.company_name,
                                role='supplier'
                            )
                        child_ctx = DDContext(
                            company_details=CompanyDetails(company_name=canonical_supplier),
                            use_mock=current_ctx.use_mock,
                            tiers_to_search=current_ctx.tiers_to_search - 1,
                            max_suppliers_per_node=current_ctx.max_suppliers_per_node,
                            entity_role='supplier',
                            parent_entity=current_ctx.company_details.company_name,
                            run_id=current_ctx.run_id,
                            retrieval_engine=current_ctx.retrieval_engine,
                            ingestion_pipeline=current_ctx.ingestion_pipeline,
                            cache_gate=current_ctx.cache_gate,
                            singleflight=current_ctx.singleflight,
                            background_tasks=current_ctx.background_tasks,
                        )
                        # Assign by reference AFTER construction to bypass Pydantic's deep copy
                        child_ctx.execution_log = current_ctx.execution_log
                        child_ctx.detailed_audit_log = current_ctx.detailed_audit_log
                        child_ctx.visited_companies = current_ctx.visited_companies
                        child_ctx.visited_lock = current_ctx.visited_lock
                        child_ctx.screened_entities = current_ctx.screened_entities
                        child_ctx.screened_entities_lock = current_ctx.screened_entities_lock
                        current_ctx.log(f"SYSTEM: Spawning sub-pipeline for supplier: {canonical_supplier}")
                        task = asyncio.create_task(run_dd_with_ctx(child_ctx))
                        current_ctx.child_tasks.append(task)
                    else:
                        current_ctx.log(f"SYSTEM: Supplier {canonical_supplier} already visited. Linking edge only.")
                        stub = DDReport(
                            vendor_name=canonical_supplier, overall_risk=Severity.INFO,
                            strengths=[], red_flags=[], recommendations=[], sources=[],
                            executive_summary="Duplicate node (already researched elsewhere in graph)."
                        )
                        async def return_stub_child(s=stub): return s
                        current_ctx.child_tasks.append(asyncio.create_task(return_stub_child()))

        # Pre-warm the entity resolver cache so all 9 agents hit memory instead of Neo4j on their first search
        if ctx.retrieval_engine and ctx.retrieval_engine.resolver:
            ctx.log("SYSTEM: Pre-warming entity resolver cache...")
            await ctx.retrieval_engine.resolver.resolve_entity(ctx.company_details.company_name, ctx.run_id)

        # Optimization 2: Dynamic Search Budget
        # Complex public companies (have CIK or known to be big) get 3. Others get 2. Local/small could get 1.
        has_cik = bool(ctx.company_details.cik)
        is_tech_corp = "Tech Corp" in ctx.company_details.company_name
        ctx.search_budget = 3 if (has_cik or is_tech_corp) else 2
        ctx.log(f"SYSTEM: Assigned dynamic search budget of {ctx.search_budget} per agent.")

        # 1. Run the adaptive pipeline asynchronously.
        ctx = await engine.run(ctx, on_step_complete=handle_step_complete)

        # 2. Synthesise the final report from all accumulated results.
        report = await summary_agent.synthesise(ctx)
        
        # Track visitation
        async with ctx.visited_lock:
            ctx.visited_companies.add(ctx.company_details.company_name.lower())

        # Wait for all dynamically spawned child pipelines to finish
        if ctx.child_tasks:
            ctx.log(f"SYSTEM: Awaiting {len(ctx.child_tasks)} sub-pipelines for suppliers...")
            results = await asyncio.gather(*ctx.child_tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, Exception):
                    ctx.log(f"SYSTEM: Child pipeline failed with: {res}")
                elif res:
                    report.supply_chain.append(res)
            
        if ctx.parent_task:
            ctx.log(f"SYSTEM: Awaiting sub-pipeline for parent company...")
            try:
                report.parent_company = await ctx.parent_task
            except Exception as e:
                ctx.log(f"SYSTEM: Parent pipeline failed with: {e}")

        await neo4j.save_company_node(ctx.company_details.company_name, report.overall_risk.value)
        
        # 3. Compile the full audit log using the chronological detailed_audit_log
        audit_lines = [
            f"=== AUDIT LOG FOR {ctx.company_details.company_name} ===",
            "Generated: " + datetime.now().isoformat(),
            "-" * 60,
            ""
        ]
        
        # Append the chronological events, rationales, and raw data
        audit_lines.extend(ctx.detailed_audit_log)
        
        # Append sub-report audit logs if any exist
        for sub_report in report.supply_chain:
            audit_lines.append("")
            audit_lines.append("=" * 60)
            audit_lines.append(f"=== SUPPLY CHAIN AUDIT: {sub_report.vendor_name} ===")
            audit_lines.append("=" * 60)
            audit_lines.append(sub_report.audit_log)
            
        report.audit_log = "\n".join(audit_lines)
        
        if getattr(ctx, 'checkpoint_db', None) and ctx.run_id:
            await ctx.checkpoint_db.mark_processed(ctx.run_id, ctx.company_details.company_name, "completed")
            
        return report
    except asyncio.CancelledError:
        ctx.log("SYSTEM: Cancellation received, aborting sub-pipelines...")
        if getattr(ctx, 'checkpoint_db', None) and ctx.run_id:
            await ctx.checkpoint_db.mark_processed(ctx.run_id, ctx.company_details.company_name, "cancelled")
        for task in getattr(ctx, "child_tasks", []):
            if not task.done():
                task.cancel()
        if getattr(ctx, "parent_task", None) and not ctx.parent_task.done():
            ctx.parent_task.cancel()
        raise
    except Exception:
        if getattr(ctx, 'checkpoint_db', None) and ctx.run_id:
            await ctx.checkpoint_db.mark_processed(ctx.run_id, ctx.company_details.company_name, "failed")
        raise
    finally:
        await client.close()

async def run_dd(
    vendor_name: str,
    vendor_country: str | None = None,
    vendor_registration_id: str | None = None,
    use_mock: bool = False,
) -> DDReport:
    import uuid
    from core.dependencies import (
        retrieval_engine, ingestion_pipeline,
        cache_gate, singleflight, background_tasks
    )

    run_id = str(uuid.uuid4())
    
    ctx = DDContext(
        company_details=CompanyDetails(
            company_name=vendor_name,
            country=vendor_country,
            registration_number=vendor_registration_id,
        ),
        use_mock=use_mock,
        run_id=run_id,
        retrieval_engine=retrieval_engine,
        ingestion_pipeline=ingestion_pipeline,
        cache_gate=cache_gate,
        singleflight=singleflight,
        background_tasks=background_tasks,
    )
    return await run_dd_with_ctx(ctx)


if __name__ == "__main__":
    # Use asyncio.run() to kick off the async event loop for the entire pipeline
    report = asyncio.run(
        run_dd(
            vendor_name="Acme Components Ltd",
            vendor_country="SG",
            vendor_registration_id="UEN201912345A",
        )
    )
    print(report.model_dump_json(indent=2))
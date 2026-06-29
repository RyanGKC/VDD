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
from core.models import CompanyDetails, DDContext, DDReport, StepName
from core.neo4j_client import Neo4jClient

logging.basicConfig(level=logging.INFO)


def build_engine(openai: OpenAIClient) -> tuple[FlowEngine, SummaryAgent]:
    # Register one agent instance per step. The keys must match StepName so
    # the flow engine can look agents up by step.
    agents = {
        StepName.SHAREHOLDERS: ShareholdersAgent(openai),
        StepName.KYB: KYBAgent(openai),
        StepName.SANCTIONS: SanctionsAgent(openai),
        StepName.PROFILE: ProfileAgent(openai),
        StepName.LICENSES: LicensesAgent(openai),
        StepName.FINANCES: FinancesAgent(openai),
        StepName.RESILIENCE: ResilienceAgent(openai),
        StepName.ESG: ESGAgent(openai),
        StepName.MEDIA: MediaAgent(openai),
    }
    supervisor = SupervisorAgent(openai)
    engine = FlowEngine(agents=agents, supervisor=supervisor)
    return engine, SummaryAgent(openai)


async def run_dd_with_ctx(ctx: DDContext) -> DDReport:
    openai = OpenAIClient(model="gpt-4o-mini")
    try:
        engine, summary_agent = build_engine(openai)
        # 1. Run the adaptive pipeline asynchronously.
        ctx = await engine.run(ctx)

        # 2. Synthesise the final report from all accumulated results.
        report = await summary_agent.synthesise(ctx)
        
        # --- Supply Chain Graph & Recursion ---
        neo4j = Neo4jClient()
        await neo4j.setup_constraints()
        await neo4j.save_company_node(ctx.company_details.company_name, report.overall_risk.value)

        # Track visitation
        ctx.visited_companies.add(ctx.company_details.company_name.lower())

        if ctx.tiers_to_search > 1:
            suppliers = []
            if StepName.RESILIENCE in ctx.results:
                suppliers = ctx.results[StepName.RESILIENCE].structured_data.get("suppliers", [])
            
            # Cap the number of suppliers per tier to prevent API quota exhaustion
            suppliers = suppliers[:ctx.max_suppliers_per_node]
            
            tasks = []
            for supplier_name in suppliers:
                # Skip if we already mapped this supplier
                if supplier_name.lower() in ctx.visited_companies:
                    continue
                
                # Record the edge: supplier -> current target
                await neo4j.save_supply_edge(supplier_name, ctx.company_details.company_name)
                
                # Spawn child pipeline
                child_ctx = DDContext(
                    company_details=CompanyDetails(company_name=supplier_name),
                    use_mock=ctx.use_mock,
                    tiers_to_search=ctx.tiers_to_search - 1,
                    max_suppliers_per_node=ctx.max_suppliers_per_node,
                    visited_companies=ctx.visited_companies
                )
                ctx.log(f"SYSTEM: Spawning sub-pipeline for supplier: {supplier_name}")
                
                # Execute concurrently
                tasks.append(run_dd_with_ctx(child_ctx))
            
            if tasks:
                ctx.log(f"SYSTEM: Awaiting {len(tasks)} sub-pipelines for suppliers...")
                sub_reports = await asyncio.gather(*tasks)
                report.supply_chain.extend(sub_reports)

        await neo4j.close()
        
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
        
        return report
    finally:
        await openai.close()

async def run_dd(
    vendor_name: str,
    vendor_country: str | None = None,
    vendor_registration_id: str | None = None,
    use_mock: bool = False,
) -> DDReport:
    # Public function: run full due diligence and return the report.
    ctx = DDContext(
        company_details=CompanyDetails(
            company_name=vendor_name,
            country=vendor_country,
            registration_number=vendor_registration_id,
        ),
        use_mock=use_mock
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
import asyncio
from main import run_dd_with_ctx
from core.models import DDContext, CompanyDetails
from core.dependencies import vs, neo4j, cache_gate, singleflight, background_tasks, retrieval_engine, ingestion_pipeline

async def main():
    ctx = DDContext(
        run_id="test_opt_001",
        company_details=CompanyDetails(
            company_name="DeepMind",
            country="UK"
        ),
        enable_rag=True,
        cache_gate=cache_gate,
        singleflight=singleflight,
        background_tasks=background_tasks,
        retrieval_engine=retrieval_engine,
        ingestion_pipeline=ingestion_pipeline,
    )
    
    print("Starting optimization test...")
    report = await run_dd_with_ctx(ctx)
    print("Done! Total findings:", len(report.findings))

if __name__ == "__main__":
    asyncio.run(main())

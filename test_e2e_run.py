import asyncio
from core.models import CompanyDetails, DDContext
from main import run_dd_with_ctx
import uuid
import os

async def test():
    company_name="SpaceX"
    run_id = str(uuid.uuid4())
    print(f"Starting E2E test for {company_name} with run_id {run_id}")
    
    ctx = DDContext(
        company_details=CompanyDetails(
            company_name=company_name,
            country="USA",
            registration_number="",
        ),
        use_mock=True,
        tiers_to_search=1,
        max_suppliers_per_node=3,
        enable_parent_company=False,
        enable_parent_supply_chain=False,
        run_id=run_id,
        retrieval_engine=None,
        ingestion_pipeline=None,
        cache_gate=None,
        singleflight=None,
        background_tasks=None,
    )
    
    try:
        report = await run_dd_with_ctx(ctx)
        print("Test completed successfully!")
        print(f"Executive Summary: {report.executive_summary[:100]}...")
    except Exception as e:
        print(f"Test failed with exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())

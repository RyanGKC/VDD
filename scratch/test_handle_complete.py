import asyncio
from core.models import DDContext, CompanyDetails
from main import run_dd_with_ctx
import uuid

async def test():
    ctx = DDContext(
        company_details=CompanyDetails(
            company_name="Apple Inc",
            country="US"
        ),
        use_mock=False,
        tiers_to_search=2,
        max_suppliers_per_node=3,
        run_id=str(uuid.uuid4())
    )
    import os
    os.environ["ENABLE_RAG"] = "false"
    
    print("Running with tiers_to_search=2...")
    report = await run_dd_with_ctx(ctx)
    print("Child tasks in ctx:", len(ctx.child_tasks))
    print("Supply chain len:", len(report.supply_chain))

asyncio.run(test())

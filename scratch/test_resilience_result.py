import asyncio
from core.models import DDContext, CompanyDetails, StepName
from main import run_dd_with_ctx
import uuid
import os

async def test():
    ctx = DDContext(
        company_details=CompanyDetails(company_name="Apple Inc", country="US"),
        use_mock=False,
        tiers_to_search=2,
        max_suppliers_per_node=3,
        run_id=str(uuid.uuid4())
    )
    
    os.environ["ENABLE_RAG"] = "false"
    os.environ["PYTHONUNBUFFERED"] = "1"
    
    print("Starting test...")
    report = await run_dd_with_ctx(ctx)
    print("DONE.")
    
    print("\n--- EXECUTION LOG ---")
    for msg in ctx.execution_log:
        print(msg)

asyncio.run(test())

import asyncio
from core.models import DDContext, CompanyDetails, StepName, StepResult
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
    
    # We will just construct the engine and call handle_step_complete directly
    from main import run_dd_with_ctx
    
    # Wait, handle_step_complete is defined inside run_dd_with_ctx!
    # I can't call it directly. I'll just use my debug prints in run_dd_with_ctx.
    
    import os
    os.environ["ENABLE_RAG"] = "false"
    os.environ["PYTHONUNBUFFERED"] = "1"
    
    print("Starting test...")
    report = await run_dd_with_ctx(ctx)
    print("DONE. Child tasks:", len(ctx.child_tasks))

asyncio.run(test())

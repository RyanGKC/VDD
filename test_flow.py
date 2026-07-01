import asyncio
import os
from main import run_dd

async def test():
    # Force RAG to be disabled
    os.environ["ENABLE_RAG"] = "false"
    
    # Run the main pipeline with use_mock=True to make it fast
    # but tiers_to_search=2 to trigger resilience agent supplier logic
    import uuid
    from core.models import DDContext, CompanyDetails
    from main import run_dd_with_ctx
    from core.document_store import DocumentStore
    
    ctx = DDContext(
        company_details=CompanyDetails(
            company_name="Apple Inc",
            country="US"
        ),
        use_mock=True,
        tiers_to_search=2,
        max_suppliers_per_node=2,
        document_store=DocumentStore(str(uuid.uuid4()))
    )
    
    report = await run_dd_with_ctx(ctx)
    print("\nCHILD TASKS SPAWNED:", len(ctx.child_tasks))
    print("SUPPLY CHAIN LENGTH:", len(report.supply_chain))
    if len(report.supply_chain) > 0:
        print("First supplier:", report.supply_chain[0].vendor_name)

asyncio.run(test())

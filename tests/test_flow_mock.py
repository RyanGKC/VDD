import asyncio
import os
import pytest
from main import run_dd

@pytest.mark.asyncio
async def test():
    os.environ["ENABLE_RAG"] = "false"
    
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

asyncio.run(test())

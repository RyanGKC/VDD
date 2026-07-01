import asyncio
import os
from main import run_dd_with_ctx
from core.models import DDContext, CompanyDetails
from core.document_store import DocumentStore
import uuid

async def test():
    os.environ["ENABLE_RAG"] = "false"
    
    ctx = DDContext(
        company_details=CompanyDetails(
            company_name="Apple Inc",
            country="US"
        ),
        use_mock=False,
        tiers_to_search=2,
        max_suppliers_per_node=3,
        document_store=DocumentStore(str(uuid.uuid4()))
    )
    
    print("Running FULL pipeline with REAL tools and RAG OFF for Apple Inc...")
    try:
        report = await run_dd_with_ctx(ctx)
        print("Child tasks:", len(ctx.child_tasks))
        print("Supply chain:", [s.vendor_name for s in report.supply_chain])
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(test())

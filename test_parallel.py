import asyncio
from main import run_dd_with_ctx
from core.models import DDContext, CompanyDetails

async def run_test():
    ctx = DDContext(
        company_details=CompanyDetails(company_name="Tech Corp Risk"),
        use_mock=True,
        tiers_to_search=2,
        max_suppliers_per_node=2,
        enable_parent_company=True,
        enable_parent_supply_chain=True
    )
    
    print("Starting Mock Parallel Test...")
    report = await run_dd_with_ctx(ctx)
    print("\n\nTest Complete. Output:")
    print("Main Company:", report.vendor_name)
    if report.parent_company:
        print(f"Parent Company Researched: {report.parent_company.vendor_name}")
    print("Suppliers Researched:", len(report.supply_chain))
    for s in report.supply_chain:
        print(f"- {s.vendor_name}")

if __name__ == "__main__":
    asyncio.run(run_test())

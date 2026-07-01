import asyncio
import os
from agents.resilience_agent import ResilienceAgent
from core.models import DDContext, CompanyDetails
from core.gemini_client import GeminiClient

async def test():
    os.environ["ENABLE_RAG"] = "false"
    
    ctx = DDContext(
        company_details=CompanyDetails(
            company_name="Apple Inc",
            country="US"
        ),
        use_mock=False,
    )
    
    client = GeminiClient(use_cache=False)
    agent = ResilienceAgent(client)
    
    print("Running ResilienceAgent with REAL tools and RAG OFF...")
    try:
        res = await agent.run(ctx)
        print("Suppliers extracted:", res.structured_data.get("suppliers", []))
    except Exception as e:
        print("Agent failed:", e)

asyncio.run(test())

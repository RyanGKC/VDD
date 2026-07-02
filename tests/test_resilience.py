import asyncio
from core.models import DDContext, CompanyDetails
from core.gemini_client import GeminiClient
from core.document_store import DocumentStore
from agents.resilience_agent import ResilienceAgent
import uuid

async def test():
    ctx = DDContext(
        company_details=CompanyDetails(
            company_name="Apple Inc",
            country="US"
        ),
        use_mock=False,
        document_store=DocumentStore(str(uuid.uuid4()))
    )
    client = GeminiClient(use_cache=False)
    agent = ResilienceAgent(client)
    res = await agent.run(ctx)
    print("\nFINDINGS:")
    print(res.findings)
    print("\nSTRUCTURED DATA:")
    print(res.structured_data)

asyncio.run(test())

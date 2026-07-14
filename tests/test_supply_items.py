import asyncio
from unittest.mock import AsyncMock
from core.models import DDContext, CompanyDetails
from agents.resilience_agent import ResilienceAgent, _ResilienceAnalysis, _SupplierItem, _FindingModel, _SourceModel
import pytest
from core.gemini_client import GeminiClient

@pytest.mark.asyncio
async def test_supply_items():
    # Set up mock context
    ctx = DDContext(
        company_details=CompanyDetails(
            company_name="Test Company",
            country="US"
        ),
        use_mock=True
    )
    
    client = GeminiClient(use_cache=True)
    agent = ResilienceAgent(client)
    
    # Mock the LLM call generate_with_web_search
    mock_analysis = _ResilienceAnalysis(
        rationale="Test rationale",
        findings=[
            _FindingModel(
                summary="Found supplier Global Materials Ltd supplying aluminium.",
                spof_analysis="SPOF analysis",
                geopolitical_risk_weighting="Low",
                severity="low",
                is_red_flag=False,
                is_strength=True,
                sources=[_SourceModel(title="Audit 2025", source_id="src1", publisher="Corp Audit")]
            )
        ],
        supply_items=[
            _SupplierItem(
                supplier_name="Global Materials Ltd",
                category="Raw Materials",
                description="Primary supplier of aluminium."
            ),
            _SupplierItem(
                supplier_name="Logistics Pro",
                category="Logistics",
                description="Logistics partner."
            )
        ],
        high_risk_dependency_found=False
    )
    
    agent.generate_with_web_search = AsyncMock(return_value=(mock_analysis, {"src1": "https://example.com/audit"}))
    agent._run_reverse_disclosure_loop = AsyncMock(return_value=[])
    
    # Run research
    res = await agent.research(ctx)
    
    print("STRUCTURED DATA:", res.structured_data)
    assert "supply_items" in res.structured_data
    assert "suppliers" in res.structured_data
    assert len(res.structured_data["supply_items"]) == 2
    assert res.structured_data["suppliers"] == ["Global Materials Ltd", "Logistics Pro"]
    print("Test passed successfully!")

if __name__ == "__main__":
    asyncio.run(test_supply_items())

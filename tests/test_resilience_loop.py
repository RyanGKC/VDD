import json, pytest
from unittest.mock import AsyncMock, patch, MagicMock
from core.models import DDContext, CompanyDetails
from agents.resilience_agent import (
    ResilienceAgent, _SupplierItem, _SupplierBrainstorm, _SupplierVerification
)
from core.gemini_client import GeminiClient

def make_ctx(use_mock=True):
    return DDContext(
        company_details=CompanyDetails(company_name="Acme Corp", country="US"),
        use_mock=use_mock,
    )

def make_agent():
    client = MagicMock(spec=GeminiClient)
    client.generate_structured = AsyncMock()
    agent = ResilienceAgent(client)
    agent.gemini = client
    return agent

@pytest.mark.asyncio
async def test_brainstorm_called_with_company_name():
    """Asserts self.gemini is used and the company name is referenced in the brainstorm prompt."""
    agent = make_agent()
    agent.gemini.generate_structured = AsyncMock(
        return_value=_SupplierBrainstorm(probable_suppliers=[])
    )
    await agent._run_reverse_disclosure_loop(make_ctx(), missing_count=2, previously_tried=set())
    agent.gemini.generate_structured.assert_called_once()
    call_args = agent.gemini.generate_structured.call_args
    assert "Acme Corp" in call_args.kwargs["prompt"]

@pytest.mark.asyncio
async def test_perform_web_search_called_with_ctx():
    """Asserts perform_web_search is called with (ctx, query), not just (query)."""
    agent = make_agent()
    agent.gemini.generate_structured = AsyncMock(side_effect=[
        _SupplierBrainstorm(probable_suppliers=["Nestle"]),
        _SupplierVerification(rationale="Confirmed.", is_confirmed=True, supplier_item=None),
    ])
    ctx = make_ctx()
    with patch("core.tools.perform_web_search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = json.dumps({"search_results": []})
        await agent._run_reverse_disclosure_loop(ctx, missing_count=1, previously_tried=set())
        mock_search.assert_called_once()
        args = mock_search.call_args[0]
        assert args[0] is ctx       # first positional arg must be ctx
        assert "Nestle" in args[1]  # second positional arg is the query string

@pytest.mark.asyncio
async def test_json_response_is_parsed_correctly():
    """Asserts the JSON string returned by perform_web_search is correctly parsed."""
    agent = make_agent()
    confirmed_item = _SupplierItem(supplier_name="Nestle", category="Food", description="Supplies food products.")
    agent.gemini.generate_structured = AsyncMock(side_effect=[
        _SupplierBrainstorm(probable_suppliers=["Nestle"]),
        _SupplierVerification(rationale="Confirmed.", is_confirmed=True, supplier_item=confirmed_item),
    ])
    ctx = make_ctx()
    valid_json = json.dumps({"search_results": [{"title": "Nestle supplies Acme", "snippet": "Nestle confirmed as supplier."}]})
    with patch("core.tools.perform_web_search", new_callable=AsyncMock, return_value=valid_json):
        result, _ = await agent._run_reverse_disclosure_loop(ctx, missing_count=1, previously_tried=set())
    assert len(result) == 1
    assert result[0].supplier_name == "Nestle"

@pytest.mark.asyncio
async def test_malformed_json_is_skipped():
    """Asserts that a malformed JSON search result does not crash the loop."""
    agent = make_agent()
    agent.gemini.generate_structured = AsyncMock(
        return_value=_SupplierBrainstorm(probable_suppliers=["Nestle"])
    )
    with patch("core.tools.perform_web_search", new_callable=AsyncMock, return_value="NOT_JSON"):
        result, _ = await agent._run_reverse_disclosure_loop(make_ctx(), missing_count=1, previously_tried=set())
    assert result == []

@pytest.mark.asyncio
async def test_search_exception_is_skipped():
    """Asserts that if perform_web_search raises an exception, the loop continues."""
    agent = make_agent()
    agent.gemini.generate_structured = AsyncMock(
        return_value=_SupplierBrainstorm(probable_suppliers=["Nestle"])
    )
    with patch("core.tools.perform_web_search", new_callable=AsyncMock, side_effect=Exception("Network error")):
        result, _ = await agent._run_reverse_disclosure_loop(make_ctx(), missing_count=1, previously_tried=set())
    assert result == []

@pytest.mark.asyncio
async def test_empty_brainstorm_returns_empty_list():
    """Asserts that an empty brainstorm response returns an empty list immediately."""
    agent = make_agent()
    agent.gemini.generate_structured = AsyncMock(
        return_value=_SupplierBrainstorm(probable_suppliers=[])
    )
    result, _ = await agent._run_reverse_disclosure_loop(make_ctx(), missing_count=3, previously_tried=set())
    assert result == []

@pytest.mark.asyncio
async def test_document_deep_dive_successful_extraction():
    """Asserts that _run_document_deep_dive fetches PDF and extracts suppliers."""
    agent = make_agent()
    agent.gemini.generate_structured = AsyncMock(
        return_value=_SupplierBrainstorm(probable_suppliers=["Nestle", "F&N"])
    )
    ctx = make_ctx()
    url_map = {"src_123": "https://example.com/prospectus.pdf"}
    
    with patch("custom_tools.web_search_tool.fetch_and_clean_html", new_callable=AsyncMock, return_value="Some prospectus text containing Nestle and F&N."):
        result = await agent._run_document_deep_dive(ctx, url_map)
        
    assert len(result) == 2
    assert result[0].supplier_name == "Nestle"
    assert result[1].supplier_name == "F&N"
    assert result[0].category == "Identified from official document"

@pytest.mark.asyncio
async def test_document_deep_dive_search_fallback():
    """Asserts that if url_map has no PDFs, it performs a search to find one."""
    agent = make_agent()
    agent.gemini.generate_structured = AsyncMock(
        return_value=_SupplierBrainstorm(probable_suppliers=["Nestle"])
    )
    ctx = make_ctx()
    url_map = {}
    
    search_res = json.dumps({
        "results": [{"source_url": "https://example.com/annual_report.pdf", "title": "Annual Report"}]
    })
    
    with patch("core.tools.perform_web_search", new_callable=AsyncMock, return_value=search_res) as mock_search, \
         patch("custom_tools.web_search_tool.fetch_and_clean_html", new_callable=AsyncMock, return_value="PDF text"):
        result = await agent._run_document_deep_dive(ctx, url_map)
        
    mock_search.assert_called_once()
    assert len(result) == 1
    assert result[0].supplier_name == "Nestle"

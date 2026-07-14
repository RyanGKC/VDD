import asyncio
import json
import unittest
from unittest.mock import patch, MagicMock

from core.models import DDContext, CompanyDetails, StepName
from agents.sanctions_agent import SanctionsAgent

class TestSanctionsCache(unittest.IsolatedAsyncioTestCase):
    @patch("agents.sanctions_agent.screen_sanctions")
    @patch("agents.sanctions_agent.SanctionsAgent.generate_with_web_search")
    async def test_shared_cache_prevents_duplicate_api_calls(self, mock_llm, mock_screen):
        # Setup mock returns
        mock_screen.return_value = json.dumps({
            "hits": [
                {"entity": "Acme Corp", "status": "clear"}
            ]
        })
        
        mock_llm_result = MagicMock()
        mock_llm_result.findings = []
        mock_llm_result.requires_shareholder_review = False
        mock_llm_result.new_party = None
        mock_llm_result.rationale = "Test rationale"
        mock_llm_result.model_dump.return_value = {}
        mock_llm.return_value = (mock_llm_result, {})
        
        # 1. Create a root context
        ctx = DDContext(
            company_details=CompanyDetails(company_name="Acme Corp"),
            use_mock=True
        )
        
        agent = SanctionsAgent(client=None)
        
        # First run - should call the API
        result1 = await agent.research(ctx)
        self.assertEqual(mock_screen.call_count, 1)
        mock_screen.assert_called_with(ctx, ["Acme Corp"])
        self.assertEqual(mock_llm.call_count, 1)
        
        # Verify cache was populated
        self.assertIn("acme corp", ctx.screened_entities)
        
        # 2. Create a child context that shares the cache
        child_ctx = DDContext(
            company_details=CompanyDetails(company_name="Acme Corp"),
            use_mock=True
        )
        child_ctx.screened_entities = ctx.screened_entities
        child_ctx.screened_entities_lock = ctx.screened_entities_lock
        
        # Second run - should NOT call the API or LLM because of the cache
        result2 = await agent.research(child_ctx)
        
        # Call count should still be 1!
        self.assertEqual(mock_screen.call_count, 1)
        self.assertEqual(mock_llm.call_count, 1)
        
        self.assertTrue(result2.structured_data.get("skipped"))
        self.assertIn("All entities in scope were screened", result2.rationale)

if __name__ == "__main__":
    unittest.main()

import asyncio
import unittest
from unittest.mock import MagicMock

from core.flow_engine import FlowEngine
from core.models import DDContext, CompanyDetails, StepName, StepResult

class FailingAgent:
    def __init__(self, step_name):
        self.step = step_name
        self.run_count = 0

    async def run(self, ctx: DDContext) -> StepResult:
        self.run_count += 1
        raise ValueError("Intentional simulated agent failure")

class TestFlowEngineRetries(unittest.IsolatedAsyncioTestCase):
    async def test_immediate_retries(self):
        # Setup context
        ctx = DDContext(company_details=CompanyDetails(company_name="Fail Corp"), use_mock=True)
        
        # Setup mock agents mapping
        mock_agents = {}
        for step in StepName:
            mock_agents[step] = MagicMock()
            
        # We only want to test the Shareholders agent (the first step)
        failing_agent = FailingAgent(StepName.SHAREHOLDERS)
        mock_agents[StepName.SHAREHOLDERS] = failing_agent
        
        mock_supervisor = MagicMock()
        engine = FlowEngine(agents=mock_agents, supervisor=mock_supervisor)
        
        # Run just the shareholders step through _execute_dag
        step_execution_counts = {}
        completed = await engine._execute_dag([StepName.SHAREHOLDERS], ctx, step_execution_counts)
        
        # Assertions
        # 1. The failing agent should have been called exactly 3 times
        self.assertEqual(failing_agent.run_count, 3)
        
        # 2. It should be marked as completed
        self.assertIn(StepName.SHAREHOLDERS, completed)
        
        # 3. The failure StepResult should have been injected into ctx.results
        self.assertIn(StepName.SHAREHOLDERS, ctx.results)
        result = ctx.results[StepName.SHAREHOLDERS]
        self.assertTrue(result.structured_data.get("failed"))
        self.assertIn("AGENT CRASH", result.raw_data)
        
        # 4. Check the logs
        logs = "\n".join(ctx.execution_log)
        self.assertIn("Immediately retrying shareholders", logs)
        self.assertIn("exhausted all retries and has permanently failed", logs)

if __name__ == "__main__":
    unittest.main()

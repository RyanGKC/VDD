import asyncio
import unittest
import json
from unittest.mock import MagicMock

from core.checkpoint_db import CheckpointDB
from core.models import DDContext, CompanyDetails, StepName, StepResult

import os

class TestCheckpointDB(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_path = "test_checkpoint.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.db = CheckpointDB(self.db_path)

    async def asyncTearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    async def test_checkpointing_lifecycle(self):
        run_id = "test_run_123"
        vendor = "Test Corp"
        details = CompanyDetails(company_name=vendor)
        
        # 1. Start a run
        await self.db.start_run(run_id, vendor, details.model_dump_json())
        
        run_record = await self.db.get_run(run_id)
        self.assertIsNotNone(run_record)
        self.assertEqual(run_record["status"], "running")
        
        # 2. Save some step results
        mock_result_1 = StepResult(step=StepName.SHAREHOLDERS, findings=[])
        mock_result_2 = StepResult(step=StepName.KYB, findings=[])
        
        await self.db.save_step_result(run_id, vendor, StepName.SHAREHOLDERS.value, mock_result_1.model_dump_json())
        await self.db.save_step_result(run_id, vendor, StepName.KYB.value, mock_result_2.model_dump_json())
        
        completed_steps = await self.db.get_completed_steps(run_id, vendor)
        self.assertEqual(len(completed_steps), 2)
        self.assertIn(StepName.SHAREHOLDERS.value, completed_steps)
        self.assertIn(StepName.KYB.value, completed_steps)
        
        # 3. Simulate queueing entities
        await self.db.enqueue_entity(run_id, "Target", 1, None, "target")
        await self.db.enqueue_entity(run_id, "Supplier A", 1, "Target", "supplier")
        
        pending = await self.db.get_pending_entities(run_id)
        self.assertEqual(len(pending), 2)
        
        # 4. Mark one as in progress
        await self.db.mark_in_progress(run_id, "Target")
        pending_after = await self.db.get_pending_entities(run_id)
        self.assertEqual(len(pending_after), 1)
        self.assertEqual(pending_after[0]["entity_name"], "Supplier A")
        
        # 5. Simulate a crash and reset
        await self.db.reset_in_progress(run_id)
        pending_reset = await self.db.get_pending_entities(run_id)
        self.assertEqual(len(pending_reset), 2)  # Target should be pending again
        
        # 6. Complete the run
        await self.db.complete_run(run_id)
        run_record_completed = await self.db.get_run(run_id)
        self.assertEqual(run_record_completed["status"], "completed")

if __name__ == "__main__":
    unittest.main()

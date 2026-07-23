import asyncio, tempfile, os
from core.audit_logger import AuditLogger, EventType

def _logger():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    return AuditLogger(db_path=path), path

def test_log_supervisor_review_roundtrips():
    logger, _ = _logger()
    async def go():
        await logger.log_supervisor_review(
            run_id="run1", review_round=1, is_anomaly=True,
            rationale="Media used low-relevance sources; re-run.",
            steps_to_run=["media", "finances"], updated_params={"country": "United Kingdom"},
            verification_searches=2, entity_name="Acme", entity_role="root",
        )
    asyncio.run(go())
    events = logger._chain_for_run_sync("run1")
    assert len(events) == 1
    e = events[0]
    assert e["event_type"] == "supervisor_review"
    assert e["agent_id"] == "supervisor"
    assert e["status"] == "anomaly"
    assert e["payload"]["round"] == 1
    assert e["payload"]["steps_to_run"] == ["media", "finances"]
    assert e["payload"]["updated_params"]["country"] == "United Kingdom"

def test_dag_node_carries_replan_reason():
    logger, _ = _logger()
    async def go():
        await logger.log_dag_node(
            run_id="run2", agent_id="media", event_type=EventType.DAG_NODE_START,
            replan_reason="Re-run against tier-1 outlets.",
        )
    asyncio.run(go())
    e = logger._chain_for_run_sync("run2")[0]
    assert e["payload"]["replan_reason"] == "Re-run against tier-1 outlets."

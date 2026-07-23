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

class _FakeCtx:
    def __init__(self, logger, run_id):
        self.audit_logger = logger; self.run_id = run_id
        self.entity_role = "root"; self.audit_pipeline_event_id = None
        self.results = {}; self.enrichment = {}; self.execution_log = []
        class _CD: company_name = "Acme"
        self.company_details = _CD()
    def log(self, *a, **k): pass
    def audit(self, *a, **k): pass

def test_supervisor_logs_review_event(monkeypatch):
    logger, _ = _logger()
    from agents import supervisor_agent as sa
    # Stub the LLM + neo4j so review() runs offline and returns a clear decision.
    async def fake_gen(**kwargs):
        schema = kwargs["schema"]
        if schema is sa._ReviewPlan: return sa._ReviewPlan(research_plan=[])
        return sa._ReviewDecision(is_anomaly=False, rationale="All consistent.", steps_to_run=[])
    class _Client:
        async def generate_structured(self, **k): return await fake_gen(**k)
    import rag.rate_limiter as rl
    monkeypatch.setattr(rl, "run_foreground_generation", lambda fn: fn(), raising=False)
    class _Neo:
        async def get_risky_neighbors(self, *a, **k): return []
    import core.dependencies as deps
    monkeypatch.setattr(deps, "neo4j", _Neo(), raising=False)

    sup = sa.SupervisorAgent(_Client())
    ctx = _FakeCtx(logger, "run3")
    asyncio.run(sup.review(ctx=ctx, completed=set(), review_round=1))
    revs = [e for e in logger._chain_for_run_sync("run3") if e["event_type"] == "supervisor_review"]
    assert len(revs) == 1 and revs[0]["payload"]["is_anomaly"] is False

def test_generation_extra_merges_into_payload():
    logger, _ = _logger()
    async def go():
        await logger.log_generation(
            run_id="run4", agent_id="summary_agent_contradiction",
            claim="Contradiction check", supporting_chunk_ids=[], model_version="x",
            extra={"removed_findings": ["Company is privately held"]},
        )
    asyncio.run(go())
    e = logger._chain_for_run_sync("run4")[0]
    assert e["payload"]["removed_findings"] == ["Company is privately held"]

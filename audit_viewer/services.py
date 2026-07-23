from collections import Counter
from typing import List

from core.audit_logger import AuditEvent, EventType
from core.dependencies import audit_logger
from core.models import DAG_DEPENDENCIES
from .models import AuditSummary, AuditTrailResponse, Chunk, Edge, EntityScope, RawChunksResponse


def _dict_to_audit_event(data: dict) -> AuditEvent:
    return AuditEvent(
        event_id=data.get("event_id", ""), run_id=data.get("run_id", ""),
        agent_id=data.get("agent_id", ""), event_type=EventType(data.get("event_type")),
        parent_event_id=data.get("parent_event_id"), model_version=data.get("model_version"),
        prompt_version=data.get("prompt_version"), payload=data.get("payload") or {},
        timestamp=data.get("timestamp", ""), entity_name=data.get("entity_name"),
        entity_role=data.get("entity_role"), status=data.get("status"),
    )


def build_audit_graph(run_id: str, company_name: str | None = None, db_path: str = "structured_audit.db") -> AuditTrailResponse:
    """Return the complete run. Entity filtering is intentionally a UI concern.

    Older events have no entity scope; they are attributed to the requested company
    so historical audit logs remain usable.
    """
    events = [_dict_to_audit_event(row) for row in audit_logger._chain_for_run_sync(run_id)]
    for event in events:
        if not event.entity_name:
            event.entity_name = company_name or "Unknown entity"
            event.entity_role = event.entity_role or "legacy"

    edges = [Edge(id=f"edge-{event.event_id}", source=event.parent_event_id, target=event.event_id)
             for event in events if event.parent_event_id]
    scopes = Counter((event.entity_name or "Unknown entity", event.entity_role or "unknown") for event in events)
    entities = [EntityScope(name=name, role=role, event_count=count) for (name, role), count in scopes.items()]
    ends = [event for event in events if event.event_type == EventType.PIPELINE_END]
    failed = [event for event in events if event.status == "failed"]
    high_risks = [event for event in events if event.event_type == EventType.RISK_FLAG
                  and str(event.payload.get("severity", "")).lower() in {"high", "critical"}]
    summary = AuditSummary(
        status=ends[-1].status if ends else "running",
        total_events=len(events),
        agents_completed=sum(1 for event in events if event.event_type == EventType.DAG_NODE_END and event.status == "completed"),
        agents_failed=len(failed),
        retrievals=sum(1 for event in events if event.event_type == EventType.RETRIEVAL),
        generations=sum(1 for event in events if event.event_type == EventType.GENERATION),
        risk_flags=sum(1 for event in events if event.event_type == EventType.RISK_FLAG),
        high_risk_flags=len(high_risks),
        evidence_events=sum(1 for event in events if event.event_type == EventType.RETRIEVAL and len(event.payload.get("chunk_ids", [])) > 0),
        started_at=events[0].timestamp if events else None,
        ended_at=ends[-1].timestamp if ends else None,
    )
    dag_dependencies = {step.value: [dep.value for dep in deps] for step, deps in DAG_DEPENDENCIES.items()}
    return AuditTrailResponse(events=events, edges=edges, entities=entities, dag_dependencies=dag_dependencies, summary=summary)


def fetch_raw_chunks(event_id: str, db_path: str = "structured_audit.db") -> RawChunksResponse:
    evidence = audit_logger._evidence_for_event_sync(event_id)
    return RawChunksResponse(chunks=[Chunk(**item) for item in evidence], available=bool(evidence))

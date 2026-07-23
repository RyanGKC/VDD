from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from core.audit_logger import AuditEvent


class Node(BaseModel):
    id: str
    label: str


class Edge(BaseModel):
    id: str
    source: str
    target: str


class EntityScope(BaseModel):
    name: str
    role: str = "unknown"
    event_count: int = 0


class AuditSummary(BaseModel):
    status: str = "unknown"
    total_events: int = 0
    agents_completed: int = 0
    agents_failed: int = 0
    retrievals: int = 0
    generations: int = 0
    risk_flags: int = 0
    high_risk_flags: int = 0
    evidence_events: int = 0
    started_at: Optional[str] = None
    ended_at: Optional[str] = None


class AuditTrailResponse(BaseModel):
    events: List[AuditEvent] = Field(default_factory=list)
    edges: List[Edge] = Field(default_factory=list)
    entities: List[EntityScope] = Field(default_factory=list)
    dag_dependencies: Dict[str, List[str]] = Field(default_factory=dict)
    summary: AuditSummary = Field(default_factory=AuditSummary)


# Kept as an alias for imports in any local prototype integrations.
AuditGraphResponse = AuditTrailResponse


class Chunk(BaseModel):
    id: str
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RawChunksResponse(BaseModel):
    chunks: List[Chunk] = Field(default_factory=list)
    available: bool = True

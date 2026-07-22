from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from core.audit_logger import AuditEvent

class Node(BaseModel):
    id: str
    label: str

class Edge(BaseModel):
    id: str
    source: str
    target: str

class AuditGraphResponse(BaseModel):
    nodes: List[Node]
    edges: List[Edge]
    event_groups: Dict[str, List[AuditEvent]]

class Chunk(BaseModel):
    id: str
    text: str
    metadata: Dict[str, Any]

class RawChunksResponse(BaseModel):
    chunks: List[Chunk]

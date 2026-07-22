import logging
from typing import List, Dict, Set
from collections import defaultdict

from core.audit_logger import AuditLogger, AuditEvent, EventType
from rag.vector_store import VectorStore
from .models import AuditGraphResponse, Node, Edge, RawChunksResponse, Chunk

logger = logging.getLogger(__name__)

def _dict_to_audit_event(data: dict) -> AuditEvent:
    return AuditEvent(
        event_id=data.get("event_id", ""),
        run_id=data.get("run_id", ""),
        agent_id=data.get("agent_id", ""),
        event_type=EventType(data.get("event_type")),
        parent_event_id=data.get("parent_event_id"),
        model_version=data.get("model_version"),
        prompt_version=data.get("prompt_version"),
        payload=data.get("payload") if isinstance(data.get("payload"), dict) else {},
        timestamp=data.get("timestamp", "")
    )

def build_audit_graph(run_id: str, company_name: str, db_path: str = "structured_audit.db") -> AuditGraphResponse:
    audit_log = AuditLogger(db_path=db_path)
    raw_events = audit_log._chain_for_run_sync(run_id)
    all_events = [_dict_to_audit_event(e) for e in raw_events]
    
    # 1. Find the root PIPELINE_START for this specific company
    root_event = None
    for e in all_events:
        if e.event_type == EventType.PIPELINE_START and e.payload.get("company_name") == company_name:
            root_event = e
            # Don't break — keep scanning to find the LAST pipeline_start for this company.
            # React Strict Mode can fire duplicate requests, creating multiple pipeline_start
            # events for the same run. ctx.enrichment stores the LAST one's event_id,
            # so agents link their parent_event_id to it. We must match.
            
    if not root_event:
        return AuditGraphResponse(nodes=[], edges=[], event_groups={})
        
    # 2. Build adjacency list to find descendants
    children_map = defaultdict(list)
    for e in all_events:
        if e.parent_event_id:
            children_map[e.parent_event_id].append(e)
            
    # 3. Traverse to collect only events in this company's sub-pipeline
    relevant_events = []
    to_visit = [root_event]
    
    while to_visit:
        curr = to_visit.pop(0)
        
        # Don't recurse into other sub-pipelines
        if curr != root_event and curr.event_type == EventType.PIPELINE_START:
            continue
            
        relevant_events.append(curr)
        to_visit.extend(children_map[curr.event_id])
        
    # Fallback: adopt orphaned dag_node_start events that have no parent.
    # This can happen when ctx.enrichment["_current_start_event_id"] was lost
    # (e.g., checkpoint resume) or when agents ran before the pipeline_start
    # event_id was propagated.
    reachable_ids = {e.event_id for e in relevant_events}
    for e in all_events:
        if (e.event_type == EventType.DAG_NODE_START 
                and not e.parent_event_id 
                and e.event_id not in reachable_ids):
            relevant_events.append(e)
            reachable_ids.add(e.event_id)
            # Also adopt this orphan's children
            to_visit = list(children_map[e.event_id])
            while to_visit:
                child = to_visit.pop(0)
                if child.event_id not in reachable_ids:
                    relevant_events.append(child)
                    reachable_ids.add(child.event_id)
                    to_visit.extend(children_map[child.event_id])
        
    # 4. Group events by agent_id and define Nodes
    event_groups = defaultdict(list)
    for e in relevant_events:
        event_groups[e.agent_id].append(e)
        
    # Standardize nodes
    nodes = []
    for agent_id in event_groups.keys():
        label = agent_id.replace("_", " ").title()
        nodes.append(Node(id=agent_id, label=label))
        
    # 5. Define Edges (Basic Sequential DAG based on VDD logic)
    edges = []
    agent_nodes = [n for n in nodes if n.id not in ("system", "entity_resolver", "summary_agent", "cache_gate")]
    
    if "system" in event_groups:
        if "entity_resolver" in event_groups:
            edges.append(Edge(id="sys-res", source="system", target="entity_resolver"))
            for a in agent_nodes:
                edges.append(Edge(id=f"res-{a.id}", source="entity_resolver", target=a.id))
        else:
            for a in agent_nodes:
                edges.append(Edge(id=f"sys-{a.id}", source="system", target=a.id))
                
        if "summary_agent" in event_groups:
            for a in agent_nodes:
                edges.append(Edge(id=f"{a.id}-sum", source=a.id, target="summary_agent"))
            edges.append(Edge(id="sum-sys_end", source="summary_agent", target="system"))
            
    return AuditGraphResponse(
        nodes=nodes,
        edges=edges,
        event_groups=dict(event_groups)
    )

def fetch_raw_chunks(chunk_ids: List[str]) -> RawChunksResponse:
    if not chunk_ids:
        return RawChunksResponse(chunks=[])

    vs = VectorStore()
    chunks = []
    seen_ids: Set[str] = set()
    
    for collection_name in ["run_documents", "historical_reports"]:
        try:
            collection = vs.get_collection(collection_name)
            res = collection.get(ids=chunk_ids)
            if res and res.get("documents"):
                docs = res["documents"]
                metas = res.get("metadatas") or [{}] * len(docs)
                ids = res.get("ids") or []
                
                for i, doc in enumerate(docs):
                    c_id = ids[i] if i < len(ids) else f"unknown_{i}"
                    if c_id not in seen_ids:
                        seen_ids.add(c_id)
                        chunks.append(Chunk(
                            id=c_id,
                            text=doc,
                            metadata=metas[i] if i < len(metas) else {}
                        ))
        except Exception as e:
            logger.error(f"Error fetching chunks from {collection_name}: {e}")
            
    return RawChunksResponse(chunks=chunks)

import asyncio
import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class EventType(str, Enum):
    """
    Defines the distinct types of events recorded in the audit trail.
    These map to specific actions taken by the agents in the pipeline.
    """
    PIPELINE_START = "pipeline_start"  # When a full research pipeline is initiated
    PIPELINE_END = "pipeline_end"      # When a full research pipeline completes
    DAG_NODE_START = "dag_node_start"  # When an agent begins its execution phase
    DAG_NODE_END = "dag_node_end"      # When an agent finishes its execution phase
    RETRIEVAL = "retrieval"            # When an agent fetches data (web search, cache hit, or RAG)
    TOOL_CALL = "tool_call"            # When an agent invokes a specific tool (e.g., custom integrations)
    GENERATION = "generation"          # When an LLM generates a claim, rationale, or structured data
    RISK_FLAG = "risk_flag"            # When a finding is identified as a risk or anomaly


@dataclass
class AuditEvent:
    """
    Represents a single, immutable event in the audit trail.
    
    Attributes:
        run_id: Uniquely identifies the pipeline execution run (shared across target and suppliers).
        agent_id: The identifier of the agent performing the action (e.g., 'kyb', 'sanctions').
        event_type: The category of the event (EventType).
        payload: A dictionary of context-specific data for the event (e.g., search queries, generated text).
        parent_event_id: The event_id of the preceding causal event, forming a causal tree.
        model_version: The LLM model string used, applicable mainly to GENERATION events.
        prompt_version: Reserved for future tracking of prompt templates.
        event_id: A unique UUID for this specific event.
        timestamp: An ISO-8601 UTC timestamp of when the event occurred.
    """
    run_id: str
    agent_id: str
    event_type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    parent_event_id: Optional[str] = None
    model_version: Optional[str] = None
    prompt_version: Optional[str] = None
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    parent_event_id TEXT,
    model_version TEXT,
    prompt_version TEXT,
    payload TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_run_id ON audit_events(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_agent_id ON audit_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_events(event_type);
"""


class AuditLogger:
    """
    A structured, SQLite-backed audit logger for compliance tracking.
    
    This logger creates a chronological, queryable chain of custody for all AI actions.
    To prevent blocking the asyncio event loop, all database writes are dispatched 
    to a background ThreadPoolExecutor.
    """
    def __init__(self, db_path: str = "structured_audit.db"):
        """
        Initializes the SQLite database, creating the schema if it does not exist.
        """
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._executor = ThreadPoolExecutor(max_workers=1)

    async def _run_in_executor(self, func, *args):
        """Helper to run synchronous functions in the thread pool."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, func, *args)

    def _log_sync(self, event: AuditEvent) -> str:
        """Synchronously inserts an AuditEvent into the SQLite database."""
        self._conn.execute(
            """INSERT INTO audit_events
               (event_id, run_id, agent_id, event_type, parent_event_id,
                model_version, prompt_version, payload, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.event_id,
                event.run_id,
                event.agent_id,
                event.event_type.value,
                event.parent_event_id,
                event.model_version,
                event.prompt_version,
                json.dumps(event.payload, default=str),
                event.timestamp,
            ),
        )
        self._conn.commit()
        return event.event_id

    async def log(self, event: AuditEvent) -> str:
        """
        Asynchronously logs a generic AuditEvent.
        Returns the generated event_id.
        """
        return await self._run_in_executor(self._log_sync, event)

    async def log_pipeline_start(self, run_id: str, company_name: str, config: dict[str, Any]) -> str:
        """Logs the initialization of a full pipeline run."""
        return await self.log(
            AuditEvent(
                run_id=run_id,
                agent_id="system",
                event_type=EventType.PIPELINE_START,
                payload={"company_name": company_name, "config": config},
            )
        )

    async def log_pipeline_end(self, run_id: str, status: str, parent_event_id: Optional[str] = None) -> str:
        """Logs the completion of a full pipeline run."""
        return await self.log(
            AuditEvent(
                run_id=run_id,
                agent_id="system",
                event_type=EventType.PIPELINE_END,
                parent_event_id=parent_event_id,
                payload={"status": status},
            )
        )

    async def log_dag_node(
        self,
        run_id: str,
        agent_id: str,
        event_type: EventType,
        findings_count: int = 0,
        anomaly: Optional[str] = None,
        parent_event_id: Optional[str] = None,
    ) -> str:
        """
        Logs the start or completion of a DAG node (agent execution).
        
        Args:
            run_id: The ID of the pipeline run.
            agent_id: The step name of the agent (e.g., 'kyb').
            event_type: Either EventType.DAG_NODE_START or EventType.DAG_NODE_END.
            findings_count: (Optional) The number of findings produced by the agent.
            anomaly: (Optional) A string description of any anomaly detected.
            parent_event_id: (Optional) The ID of the causal event (typically DAG_NODE_START).
            
        Returns:
            The newly created event_id.
        """
        payload = {"findings_count": findings_count}
        if anomaly:
            payload["anomaly"] = anomaly
        return await self.log(
            AuditEvent(
                run_id=run_id,
                agent_id=agent_id,
                event_type=event_type,
                parent_event_id=parent_event_id,
                payload=payload,
            )
        )

    async def log_retrieval(
        self,
        run_id: str,
        agent_id: str,
        query: str,
        chunk_ids: list[str],
        source_domains: list[str],
        relevance_scores: list[float],
        parent_event_id: Optional[str] = None,
    ) -> str:
        """
        Logs a data retrieval action, such as a web search or RAG query.
        
        Args:
            run_id: The ID of the pipeline run.
            agent_id: The agent performing the retrieval.
            query: The search string or query intent used.
            chunk_ids: List of unique identifiers for the retrieved documents.
            source_domains: List of domains from which data was retrieved.
            relevance_scores: List of relevance scores matching the chunk_ids.
            parent_event_id: The ID of the causal event (e.g., DAG_NODE_START).
            
        Returns:
            The newly created event_id.
        """
        return await self.log(
            AuditEvent(
                run_id=run_id,
                agent_id=agent_id,
                event_type=EventType.RETRIEVAL,
                parent_event_id=parent_event_id,
                payload={
                    "query": query,
                    "chunk_ids": chunk_ids,
                    "source_domains": source_domains,
                    "relevance_scores": relevance_scores,
                },
            )
        )

    async def log_generation(
        self,
        run_id: str,
        agent_id: str,
        claim: str,
        supporting_chunk_ids: list[str],
        model_version: str,
        prompt_version: Optional[str] = None,
        parent_event_id: Optional[str] = None,
    ) -> str:
        """
        Logs text, rationales, or structured data generated by the LLM.
        
        Args:
            run_id: The ID of the pipeline run.
            agent_id: The agent performing the generation.
            claim: The actual text generated by the model (e.g., rationale).
            supporting_chunk_ids: Identifiers of the documents provided to the model in context.
            model_version: The LLM version string used (e.g., 'gemini-1.5-pro').
            prompt_version: (Optional) Tracking ID for the prompt template used.
            parent_event_id: The ID of the causal event (e.g., DAG_NODE_START).
            
        Returns:
            The newly created event_id.
        """
        return await self.log(
            AuditEvent(
                run_id=run_id,
                agent_id=agent_id,
                event_type=EventType.GENERATION,
                parent_event_id=parent_event_id,
                model_version=model_version,
                prompt_version=prompt_version,
                payload={
                    "claim": claim,
                    "supporting_chunk_ids": supporting_chunk_ids,
                },
            )
        )

    async def log_risk_flag(
        self,
        run_id: str,
        agent_id: str,
        risk_type: str,
        detail: str,
        confidence: float,
        parent_event_id: Optional[str] = None,
    ) -> str:
        """
        Logs a specific risk or anomaly identified by the agent during generation.
        
        Args:
            run_id: The ID of the pipeline run.
            agent_id: The agent identifying the risk.
            risk_type: Category of the risk (e.g., 'sanctions', 'anomaly').
            detail: Detailed description of what triggered the risk flag.
            confidence: Float representing the agent's confidence in this risk flag (0.0 to 1.0).
            parent_event_id: The ID of the generation event that produced this flag.
            
        Returns:
            The newly created event_id.
        """
        return await self.log(
            AuditEvent(
                run_id=run_id,
                agent_id=agent_id,
                event_type=EventType.RISK_FLAG,
                parent_event_id=parent_event_id,
                payload={
                    "risk_type": risk_type,
                    "detail": detail,
                    "confidence": confidence,
                },
            )
        )

    def _chain_for_run_sync(self, run_id: str) -> list[dict[str, Any]]:
        """Synchronously retrieves the complete chronological event history for a given run_id."""
        rows = self._conn.execute(
            """SELECT event_id, agent_id, event_type, parent_event_id,
                      model_version, prompt_version, payload, timestamp
               FROM audit_events WHERE run_id = ? ORDER BY timestamp ASC""",
            (run_id,),
        ).fetchall()
        cols = [
            "event_id", "agent_id", "event_type", "parent_event_id",
            "model_version", "prompt_version", "payload", "timestamp",
        ]
        events = [dict(zip(cols, row)) for row in rows]
        for e in events:
            e["payload"] = json.loads(e["payload"])
        return events

    async def chain_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """
        Asynchronously retrieves the complete chronological event history for a given run_id.
        This provides a full chain of custody across all agents and sub-pipelines for a run.
        """
        return await self._run_in_executor(self._chain_for_run_sync, run_id)

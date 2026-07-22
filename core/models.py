# Pydantic data contracts shared across all agents.

from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field


class StepName(str, Enum):
    # Canonical names for each due-diligence research step.

    SHAREHOLDERS = "shareholders"
    KYB = "kyb"
    SANCTIONS = "sanctions"
    PROFILE = "profile"
    LICENSES = "licenses"
    FINANCES = "finances"
    RESILIENCE = "resilience"
    ESG = "esg"
    MEDIA = "media"


# DAG Dependencies mapping each step to the steps that must complete before it starts.
DAG_DEPENDENCIES: dict[StepName, list[StepName]] = {
    StepName.SHAREHOLDERS: [],
    StepName.PROFILE: [],
    StepName.FINANCES: [],
    StepName.LICENSES: [],
    StepName.KYB: [StepName.SHAREHOLDERS],
    StepName.SANCTIONS: [StepName.KYB],
    StepName.RESILIENCE: [StepName.PROFILE],
    StepName.ESG: [StepName.PROFILE],
    StepName.MEDIA: [StepName.PROFILE],
}

# The canonical list of all steps.
IDEAL_FLOW: list[StepName] = list(DAG_DEPENDENCIES.keys())


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Constrained type for LLM response schemas — OpenAI structured outputs will
# only produce one of these exact strings, preventing free-text drift.
SeverityLevel = Literal["info", "low", "medium", "high", "critical"]

# Common synonyms that LLMs may produce despite schema constraints.
# Maps normalised (lower-cased) synonym → canonical Severity member.
_SEVERITY_SYNONYMS: dict[str, Severity] = {
    "none": Severity.INFO,
    "informational": Severity.INFO,
    "negligible": Severity.INFO,
    "minor": Severity.LOW,
    "moderate": Severity.MEDIUM,
    "med": Severity.MEDIUM,
    "elevated": Severity.HIGH,
    "severe": Severity.HIGH,
    "very high": Severity.CRITICAL,
    "extreme": Severity.CRITICAL,
}


def parse_severity(raw: str) -> Severity:
    """Convert a raw severity string from LLM output into a Severity enum.

    Handles:
      1. Case-insensitive exact matches  ("Low" → Severity.LOW)
      2. Common synonyms                 ("Moderate" → Severity.MEDIUM)
      3. Falls back to Severity.INFO for truly unrecognised values
    """
    normalised = raw.strip().lower()
    # 1. Try direct enum lookup.
    try:
        return Severity(normalised)
    except ValueError:
        pass
    # 2. Try synonym table.
    if normalised in _SEVERITY_SYNONYMS:
        return _SEVERITY_SYNONYMS[normalised]
    # 3. Fallback — log-worthy but shouldn't crash the pipeline.
    import logging
    logging.getLogger(__name__).warning(
        "Unrecognised severity '%s' — defaulting to INFO", raw,
    )
    return Severity.INFO


class Source(BaseModel):
    # Tracks every source used by the agents for auditability.
    title: str
    url: str | None = None
    publisher: str | None = None
    retrieved_at: datetime = Field(default_factory=lambda:datetime.now(timezone.utc))
    snippet: str | None = None
    is_database: bool = False


class Finding(BaseModel):
    # An individual observation produced by a research agent.
    summary: str
    severity: Severity = Severity.INFO
    is_red_flag: bool = False
    is_strength: bool = False
    sources: list[Source] = Field(default_factory=list)
    category: str | None = None


class AnomalySignal(BaseModel):
    # Raised by a step when it discovers something that invalidates 
    # the assumptions of earlier steps and therefore requires re-planning.
    raised_by: StepName
    reason: str
    severity: Severity
    # Hints to the supervisor — which steps the anomaly may affect. The
    # supervisor is free to override these; they are advisory, not binding.
    suggested_revisit: list[StepName] = Field(default_factory=list)
    new_context: dict[str, Any] = Field(default_factory=dict)


class StepResult(BaseModel):
    # Uniform output contract for every research step/agent.
    step: StepName
    findings: list[Finding] = Field(default_factory=list)
    structured_data: dict[str, Any] = Field(default_factory=dict)
    sources: list[Source] = Field(default_factory=list)
    raw_data: str | None = Field(default=None, description="Raw data fetched by the agent.")
    rationale: str | None = Field(default=None, description="LLM rationale for the findings.")
    anomaly: AnomalySignal | None = None  # presence triggers re-planning
    completed_at: datetime = Field(default_factory=lambda:datetime.now(timezone.utc))


from pydantic import BaseModel, Field, ConfigDict
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

class DDContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
   # The shared, mutable working memory passed between agents.
    company_details: CompanyDetails
    # Accumulated results keyed by step.
    results: dict[StepName, StepResult] = Field(default_factory=dict)
    # Free-form context that anomalies inject (e.g. newly discovered UBOs).
    enrichment: dict[str, Any] = Field(default_factory=dict)
    # Audit trail of every step executed, including re-runs (short strings for UI).
    execution_log: list[str] = Field(default_factory=list)
    # Detailed audit trail containing rationale and raw data (not sent to frontend)
    detailed_audit_log: list[str] = Field(default_factory=list)
    # Toggle for using mock data tools vs real APIs.
    use_mock: bool = False
    # Number of supply chain tiers to map (1 = Target company only)
    tiers_to_search: int = Field(default=1, ge=1)
    # Maximum number of suppliers to investigate per node
    max_suppliers_per_node: int = Field(default=3, ge=1)
    # Track visited companies across the recursive supply chain to prevent loops
    visited_companies: set[str] = Field(default_factory=set)
    # Lock for thread/coroutine-safe mutations to visited_companies
    visited_lock: asyncio.Lock = Field(default_factory=asyncio.Lock, exclude=True)
    # Shared in-run sanctions result cache: entity_name_lower -> StepResult or raw hits
    screened_entities: dict[str, Any] = Field(default_factory=dict, exclude=True)
    # Lock for screened_entities
    screened_entities_lock: asyncio.Lock = Field(default_factory=asyncio.Lock, exclude=True)
    # Lock to prevent thundering-herd API calls when resolving website/CIK
    entity_resolution_lock: asyncio.Lock = Field(default_factory=asyncio.Lock, exclude=True)
    # Checkpoint DB reference — injected at run startup
    checkpoint_db: Any = Field(default=None, exclude=True)
    # Keep track of child pipelines spawned asynchronously mid-DAG
    child_tasks: list[asyncio.Task] = Field(default_factory=list, exclude=True)
    # Parent company options
    enable_parent_company: bool = False
    enable_parent_supply_chain: bool = False
    parent_task: asyncio.Task | None = Field(default=None, exclude=True)
    # Role of this entity in the graph: 'root', 'supplier', or 'parent'
    entity_role: str = Field(default='root')
    # Name of the entity that spawned this context (for edge drawing)
    parent_entity: str | None = Field(default=None)
    # Shared document store for the entire run (Document RAG)
    run_id: str | None = Field(default=None, exclude=True)
    retrieval_engine: Any = Field(default=None, exclude=True)
    ingestion_pipeline: Any = Field(default=None, exclude=True)
    enable_rag: bool = Field(default_factory=lambda: os.getenv("ENABLE_RAG", "true").lower() == "true")
    # Async RAG orchestration layer
    cache_gate: Any = Field(default=None, exclude=True)
    search_budget: int = Field(default=3, description="Dynamically allocated max web searches per agent")
    singleflight: Any = Field(default=None, exclude=True)
    background_tasks: Any = Field(default=None, exclude=True)
    saved_to_history: bool = Field(default=False, exclude=True)
    # Structured SQLite audit logger (compliance chain of custody)
    audit_logger: Any = Field(default=None, exclude=True)

    def log(self, message: str) -> None:
        stamped = f"{datetime.now(timezone.utc).isoformat()} | {message}"
        self.execution_log.append(stamped)
        self.detailed_audit_log.append(stamped)
        
    def log_event(self, entity: str, agent: str, status: str) -> None:
        import json
        event = {"entity": entity, "agent": agent, "status": status, "role": self.entity_role, "parent_entity": self.parent_entity}
        message = f"[EVENT] {json.dumps(event)}"
        stamped = f"{datetime.now(timezone.utc).isoformat()} | {message}"
        self.execution_log.append(stamped)
        
    def audit(self, message: str) -> None:
        """Log detailed information exclusively to the downloadable audit file, not the UI."""
        stamped = f"{datetime.now(timezone.utc).isoformat()} | {message}"
        self.detailed_audit_log.append(stamped)


class CompanyDetails(BaseModel):
    # Details about the company being investigated.
    company_name: str = Field(description="The full registered name of the company.", frozen=True)
    registration_number: str | None = Field(
        None, description="The company's official registration number."
    )
    country: str | None = Field(
        None, description="The country where the company is registered."
    )
    address: str | None = Field(None, description="The registered address of the company.")
    website: str | None = Field(None, description="The official website of the company.")
    tax_id: str | None = Field(None, description="The company's tax identification number.")
    cik: str | None = Field(None, description="SEC Central Index Key for US companies.")
    company_number: str | None = Field(None, description="Companies House number for UK companies.")


class SupplierItem(BaseModel):
    # A direct supplier of this company and what it provides.
    supplier_name: str
    category: str
    description: str


class DDReport(BaseModel):
    # The final deliverable.
    vendor_name: str
    overall_risk: Severity
    strengths: list[Finding]
    red_flags: list[Finding]
    recommendations: list[str]
    sources: list[Source]
    executive_summary: str
    audit_log: str = Field(default="", description="The complete text of the raw data and agent rationales.")
    # Per-step risk scores (0–100) derived from actual agent findings.
    step_risk_scores: dict[str, int] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda:datetime.now(timezone.utc))
    # Supply chain recursive reports
    supply_chain: list['DDReport'] = Field(default_factory=list)
    # Parent company report
    parent_company: 'DDReport | None' = None
    raw_sources_by_step: dict[str, str] = Field(default_factory=dict)
    # New: direct (Tier-1) supplier items, populated from ResilienceAgent
    supply_items: list[SupplierItem] = Field(default_factory=list)
    has_identifiable_third_party_suppliers: bool = Field(default=True)


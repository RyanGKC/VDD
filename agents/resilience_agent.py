# Operational Resilience and Supply Chain Risk.

from __future__ import annotations

from agents.base_agent import BaseResearchAgent
from core.models import (
    AnomalySignal, DDContext, Finding, Severity, SeverityLevel, Source,
    StepName, StepResult, parse_severity,
)
from core.tools import perform_web_search

SYSTEM_INSTRUCTION = """
You are a supply chain risk analyst. Evaluate the vendor's operational resilience, 
supply chain dependencies, and geographic exposure using the provided web search data.

Identify explicit supplier companies (Tier 1 or Tier 2 dependencies, manufacturing partners, logistics partners, etc.) mentioned in the text. 
CRITICAL: You must prioritize identifying the top, most critical suppliers (e.g. highest volume, strategic importance, or largest contracts). Output their exact registered company names in the 'suppliers' list, ordered by importance.

If you discover a critical dependency on a high-risk or potentially sanctioned 
jurisdiction/entity that was not previously disclosed, set 'high_risk_dependency_found' 
to true and describe it.
"""

class ResilienceAgent(BaseResearchAgent):
    step = StepName.RESILIENCE

    @property
    def default_queries(self) -> list[str]:
        return [
            "{company} supply chain disruption cyber attack",
            "{company} operational resilience redundancy"
        ]

    async def research(self, ctx: DDContext) -> StepResult:
        company_name = ctx.company_details.company_name
        country = ctx.company_details.country
        
        # Perform web search to find operational resilience and supply chain data
        search_query = f"{company_name} supply chain dependency manufacturing locations resilience"
        data = await perform_web_search(ctx, search_query)

        analysis = await self.generate_with_web_search(
            ctx=ctx,
            system_instruction=SYSTEM_INSTRUCTION,
            base_prompt=(
                f"Vendor: {company_name}\n"
                f"Country: {country}\n"
                f"Web Search Results: {data}\n"
                "Extract any explicitly named manufacturing or software suppliers. Focus on critical dependencies. "
                "CRITICAL INSTRUCTION: You MUST populate the `suppliers` array with the exact names of ALL identified suppliers. Do not leave it empty."
            ),
            schema=_ResilienceAnalysis,
        )

        findings = [
            Finding(
                summary=f.summary,
                severity=parse_severity(f.severity),
                is_red_flag=f.is_red_flag,
                is_strength=f.is_strength,
                sources=[Source(**s.model_dump()) for s in f.sources],
            )
            for f in analysis.findings
        ]

        result = StepResult(
            step=self.step,
            findings=findings,
            structured_data=analysis.model_dump(),
            sources=[s for f in findings for s in f.sources],
            raw_data=data,
            rationale=analysis.rationale,
        )

        if analysis.high_risk_dependency_found and analysis.dependency_details:
            result.anomaly = AnomalySignal(
                raised_by=self.step,
                reason=f"High-risk supply chain dependency found: {analysis.dependency_details}",
                severity=Severity.MEDIUM,
                suggested_revisit=[StepName.SANCTIONS], 
                new_context={"supply_chain_risk": analysis.dependency_details},
            )

        return result

# --- Inline response schema for Gemini --- #
from pydantic import BaseModel, Field

class _SourceModel(BaseModel):
    title: str = Field(description="The title of the source or document.")
    url: str | None = Field(default=None, description="The URL of the source, if available.")
    publisher: str | None = Field(default=None, description="The publisher or author of the source.")

class _FindingModel(BaseModel):
    summary: str = Field(description="A concise summary of the finding.")
    spof_analysis: str = Field(description="Explicitly map any Single-Points-of-Failure (SPOFs) related to this finding (e.g., reliance on a single vendor or region).")
    geopolitical_risk_weighting: str = Field(description="Assess the geopolitical stability (tariffs, conflict zones) of the region associated with this finding.")
    severity: SeverityLevel = Field(description="Grade severity based on the combination of a mapped SPOF and a high-risk geopolitical climate (INFO, LOW, MEDIUM, HIGH, CRITICAL).")
    is_red_flag: bool = Field(description="Set to true ONLY if severity is HIGH or CRITICAL.")
    is_strength: bool = Field(default=False, description="Set to true if the finding indicates a highly resilient and diversified supply chain.")
    sources: list[_SourceModel] = Field(default_factory=list, description="The sources that support this finding.")

class _ResilienceAnalysis(BaseModel):
    rationale: str = Field(description="Detailed explanation of your reasoning. MUST be generated first.")
    findings: list[_FindingModel] = Field(description="List of specific findings.")
    suppliers: list[str] = Field(default_factory=list, description="List of exact names of supplier companies discovered in the search.")
    high_risk_dependency_found: bool = False
    dependency_details: str | None = None
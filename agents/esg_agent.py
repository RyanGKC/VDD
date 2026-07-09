# Environmental, Social, and Governance (ESG).

from __future__ import annotations

from agents.base_agent import BaseResearchAgent
from core.models import (
    AnomalySignal, DDContext, Finding, Severity, SeverityLevel, Source,
    StepName, StepResult, parse_severity,
)
from core.tools import perform_web_search

SYSTEM_INSTRUCTION = """
You are an ESG compliance analyst. Assess the vendor's Environmental, Social, 
and Governance footprint, scores, and any reported violations based on web data.

If you uncover severe, undisclosed ESG violations (e.g., modern slavery, massive 
environmental fines), set 'severe_esg_violation_found' to true and detail it.
"""

class ESGAgent(BaseResearchAgent):
    """ESG analysis agent."""

    step = StepName.ESG

    @property
    def default_queries(self) -> list[str]:
        return [
            "{company} ESG report",
            "{company} environmental violations controversy"
        ]

    async def research(self, ctx: DDContext) -> StepResult:
        company_name = ctx.company_details.company_name
        
        analysis, url_map = await self.generate_with_web_search(
            ctx=ctx,
            system_instruction=SYSTEM_INSTRUCTION,
            base_prompt=(
                f"Vendor: {company_name}\n"
                "Assess the ESG risk."
            ),
            schema=_ESGAnalysis,
        )

        findings = [
            Finding(
                summary=f.summary,
                severity=parse_severity(f.severity),
                is_red_flag=f.is_red_flag,
                is_strength=f.is_strength,
                sources=[Source(title=s.title, url=url_map.get(s.source_id), publisher=s.publisher) for s in f.sources],
            )
            for f in analysis.findings
        ]

        result = StepResult(
            step=self.step,
            findings=findings,
            structured_data=analysis.model_dump(),
            sources=[s for f in findings for s in f.sources],
            raw_data=None,
            rationale=analysis.rationale,
        )

        if analysis.severe_esg_violation_found and analysis.violation_details:
            result.anomaly = AnomalySignal(
                raised_by=self.step,
                reason=f"Severe ESG Violation: {analysis.violation_details}",
                severity=Severity.HIGH,
                suggested_revisit=[StepName.MEDIA], 
                new_context={"esg_violation": analysis.violation_details},
            )

        return result

# Inline response schema for Gemini (kept local to the agent)
from pydantic import BaseModel, Field

class _SourceModel(BaseModel):
    title: str = Field(description="The title of the source or document.")
    source_id: str | None = Field(default=None, description="The unique source_id from the web search results.")
    publisher: str | None = Field(default=None, description="The publisher or author of the source.")

class _FindingModel(BaseModel):
    summary: str = Field(description="A concise summary of the finding.")
    material_impact_assessment: str = Field(description="Determine if this finding represents mere PR/optics (greenwashing) or actual material financial/regulatory impact (e.g., massive EPA fines, confirmed slave labor).")
    severity: SeverityLevel = Field(description="Grade severity strictly against the industry_benchmark_context. Penalize only findings with actual material impact (INFO, LOW, MEDIUM, HIGH, CRITICAL).")
    is_red_flag: bool = Field(description="Set to true ONLY if severity is HIGH or CRITICAL.")
    is_strength: bool = Field(default=False, description="Set to true if the finding indicates strong ESG practices, such as carbon neutrality or excellent labor relations.")
    sources: list[_SourceModel] = Field(default_factory=list, description="The sources that support this finding.")

class _ESGAnalysis(BaseModel):
    industry_benchmark_context: str = Field(description="Explain the expected ESG baseline for the company's sector. MUST be generated first.")
    rationale: str = Field(description="Detailed explanation of your reasoning.")
    findings: list[_FindingModel] = Field(description="List of specific findings.")
    severe_esg_violation_found: bool = False
    violation_details: str | None = None
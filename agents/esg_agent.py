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
        
        # Search the web for ESG reports, greenwashing controversies, etc.
        search_query = f"{company_name} ESG sustainability report greenwashing controversy social governance"
        data = await perform_web_search(ctx, search_query)

        analysis = await self.generate_with_web_search(
            ctx=ctx,
            system_instruction=SYSTEM_INSTRUCTION,
            base_prompt=(
                f"Vendor: {company_name}\n"
                f"Web Search Results: {data}\n"
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
    url: str | None = Field(default=None, description="The URL of the source, if available.")
    publisher: str | None = Field(default=None, description="The publisher or author of the source.")

class _FindingModel(BaseModel):
    summary: str = Field(description="A concise summary of the finding.")
    severity: SeverityLevel = Field(description="The severity level of the finding (INFO, LOW, MEDIUM, HIGH, CRITICAL).")
    is_red_flag: bool = Field(description="Set to true ONLY if the finding indicates severe ESG violations, labor abuses, or major environmental fines.")
    is_strength: bool = Field(default=False, description="Set to true if the finding indicates strong ESG practices, such as carbon neutrality or excellent labor relations.")
    sources: list[_SourceModel] = Field(default_factory=list, description="The sources that support this finding.")

class _ESGAnalysis(BaseModel):
    rationale: str = Field(description="Detailed explanation of your reasoning. MUST be generated first.")
    findings: list[_FindingModel] = Field(description="List of specific findings.")
    severe_esg_violation_found: bool = False
    violation_details: str | None = None
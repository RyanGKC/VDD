# Company Profile and Operations Analysis.

from __future__ import annotations

from agents.base_agent import BaseResearchAgent
from core.models import (
    AnomalySignal, DDContext, Finding, Severity, SeverityLevel, Source,
    StepName, StepResult, parse_severity,
)
from core.tools import perform_web_search

SYSTEM_INSTRUCTION = """
You are a business intelligence analyst focusing strictly on the vendor's corporate profile. 
Assess what the company actually does, the nature of its core business model, its role in the market space, employee count, and primary products/services.

CRITICAL SCOPE LIMITS: 
- DO NOT research financial health, revenue, or profitability (handled by the Finances agent).
- DO NOT research supply chain, manufacturing dependencies, or physical locations (handled by the Resilience agent).
- DO NOT research media sentiment or scandals (handled by the Media agent).
Ensure your planned web searches are strictly bounded to general corporate information, market role, and business model validation.

Return findings with severity. If you identify that the actual business operations 
drastically differ from their claimed industry (e.g., claims to be IT, but is a 
shell company for mining), set 'drastic_model_discrepancy' to true and describe it.
"""

class ProfileAgent(BaseResearchAgent):
    step = StepName.PROFILE

    @property
    def default_queries(self) -> list[str]:
        return [
            "{company} business model products services",
            "{company} major competitors market share"
        ]

    async def research(self, ctx: DDContext) -> StepResult:
        company_name = ctx.company_details.company_name
        website = ctx.company_details.website

        analysis, url_map = await self.generate_with_web_search(
            ctx=ctx,
            system_instruction=SYSTEM_INSTRUCTION,
            base_prompt=(
                f"Vendor: {company_name}\n"
                f"Website: {website}\n"
                "Assess company profile and operations."
            ),
            schema=_ProfileAnalysis,
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

        if analysis.drastic_model_discrepancy and analysis.discrepancy_details:
            result.anomaly = AnomalySignal(
                raised_by=self.step,
                reason=f"Business model discrepancy: {analysis.discrepancy_details}",
                severity=Severity.HIGH,
                suggested_revisit=[StepName.LICENSES, StepName.ESG], 
                new_context={"true_industry": analysis.discrepancy_details},
            )

        return result


# Inline response schema for Gemini
from pydantic import BaseModel, Field

class _SourceModel(BaseModel):
    title: str = Field(description="The title of the source or document.")
    source_id: str | None = Field(default=None, description="The unique source_id from the web search results.")
    publisher: str | None = Field(default=None, description="The publisher or author of the source.")

class _FindingModel(BaseModel):
    summary: str = Field(description="A concise summary of the finding.")
    severity: SeverityLevel = Field(description="The severity level of the finding (INFO, LOW, MEDIUM, HIGH, CRITICAL).")
    is_red_flag: bool = Field(description="Set to true ONLY if the finding indicates a shell company, fake operations, or extreme discrepancies.")
    is_strength: bool = Field(default=False, description="Set to true if the finding indicates a highly established, reputable operational profile.")
    sources: list[_SourceModel] = Field(default_factory=list, description="The sources that support this finding.")

class _ProfileAnalysis(BaseModel):
    rationale: str = Field(description="Detailed explanation of your reasoning. MUST be generated first.")
    findings: list[_FindingModel] = Field(description="List of specific findings.")
    drastic_model_discrepancy: bool = False
    discrepancy_details: str | None = None
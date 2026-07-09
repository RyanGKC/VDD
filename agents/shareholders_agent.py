# Ownership and UBO analysis.

from __future__ import annotations

from agents.base_agent import BaseResearchAgent
from core.models import (
    AnomalySignal, DDContext, Finding, Severity, SeverityLevel, Source,
    StepName, StepResult, parse_severity,
)
from core.tools import fetch_corporate_registry

SYSTEM_INSTRUCTION = """
You are a corporate registry analyst. Given the vendor details and raw 
registry data, identify all Ultimate Beneficial Owners (UBOs) and major shareholders. 

Return findings with severity and cite every source used. If you identify a 
hidden or previously undisclosed UBO, set 'hidden_ubo_found' to true and 
provide the 'ubo_name'.

CRITICAL INSTRUCTION: If the entity is a publicly traded company (e.g., it files a 10-K, has an SEC CIK, or is noted as 'Publicly Traded'), do not flag the lack of a single UBO as an anomaly. Instead, list the major institutional investors or indicate that ownership is dispersed, and set 'hidden_ubo_found' to false.

If you identify a direct Corporate Parent company (i.e. a higher-level holding company or HQ that owns this subsidiary), set 'parent_company' to its official name.
"""

class ShareholdersAgent(BaseResearchAgent):
    step = StepName.SHAREHOLDERS

    @property
    def default_queries(self) -> list[str]:
        return [
            "{company} ultimate beneficial owners UBO",
            "{company} major shareholders parent company"
        ]

    async def research(self, ctx: DDContext) -> StepResult:
        company_name = ctx.company_details.company_name
        country = ctx.company_details.country

        data = await fetch_corporate_registry(ctx, company_name, country)

        analysis, url_map = await self.generate_with_web_search(
            ctx=ctx,
            system_instruction=SYSTEM_INSTRUCTION,
            base_prompt=(
                f"Vendor: {company_name}\n"
                f"Country: {country}\n"
                f"Registry Data: {data}\n"
                "Extract shareholders and UBOs."
            ),
            schema=_ShareholderAnalysis,
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

        # Note: We store the parsed shareholders in structured_data so the 
        # SanctionsAgent can easily access them later.
        structured_data = {"shareholders": [{"name": s} for s in analysis.extracted_shareholder_names]}
        if analysis.parent_company:
            structured_data["parent_company"] = analysis.parent_company

        result = StepResult(
            step=self.step,
            findings=findings,
            structured_data=structured_data,
            sources=[s for f in findings for s in f.sources],
            raw_data=data,
            rationale=analysis.rationale,
        )

        if analysis.hidden_ubo_found and analysis.ubo_name:
            result.anomaly = AnomalySignal(
                raised_by=self.step,
                reason=f"Undisclosed Ultimate Beneficial Owner found: {analysis.ubo_name}",
                severity=Severity.HIGH,
                suggested_revisit=[StepName.KYB, StepName.SANCTIONS], 
                new_context={"additional_entities": [analysis.ubo_name]},
            )

        return result


# --- Inline response schema for Gemini --- #
from pydantic import BaseModel, Field 

class _SourceModel(BaseModel):
    title: str = Field(description="The title of the source or document.")
    source_id: str | None = Field(default=None, description="The unique source_id from the web search results.")
    publisher: str | None = Field(default=None, description="The publisher or author of the source.")

class _FindingModel(BaseModel):
    summary: str = Field(description="A concise summary of the finding.")
    severity: SeverityLevel = Field(description="The severity level of the finding (INFO, LOW, MEDIUM, HIGH, CRITICAL).")
    is_red_flag: bool = Field(description="Set to true ONLY if the finding indicates hidden ownership, shell companies, or illicit shareholders.")
    is_strength: bool = Field(default=False, description="Set to true if the finding indicates highly transparent and reputable ownership.")
    sources: list[_SourceModel] = Field(default_factory=list, description="The sources that support this finding.")

class _ShareholderAnalysis(BaseModel):
    rationale: str = Field(description="Detailed explanation of your reasoning. MUST be generated first.")
    findings: list[_FindingModel] = Field(description="List of specific findings.")
    extracted_shareholder_names: list[str]
    hidden_ubo_found: bool = False
    ubo_name: str | None = None
    parent_company: str | None = Field(default=None, description="The official name of the direct corporate parent company (HQ/Holding Company) if one exists.")
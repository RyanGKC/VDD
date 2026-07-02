# Licenses and Certifications Verification.

from __future__ import annotations

import json
from agents.base_agent import BaseResearchAgent
from core.models import (
    AnomalySignal, DDContext, Finding, Severity, SeverityLevel, Source,
    StepName, StepResult, parse_severity,
)
from core.tools import verify_licenses, perform_web_search

SYSTEM_INSTRUCTION = """
You are a compliance certifications analyst. Verify the vendor's required 
licenses, ISO certifications, and trading permits using both database records 
and unstructured web search results.

Return findings. If a critical operational license is found to be revoked, 
expired, or fraudulent in either data source, set 'critical_license_revoked' 
to true and provide the 'license_details'.
"""

class LicensesAgent(BaseResearchAgent):
    step = StepName.LICENSES

    @property
    def default_queries(self) -> list[str]:
        return [
            "{company} regulatory licenses certifications",
            "{company} regulatory fines loss of license"
        ]

    async def research(self, ctx: DDContext) -> StepResult:
        company_name = ctx.company_details.company_name
        country = ctx.company_details.country

        # Hybrid approach: Query license DB AND search web for ISO/certification news
        db_data = await verify_licenses(ctx, company_name, country)
        search_query = f"{company_name} {country} ISO certification trading license permit status"
        web_data = await perform_web_search(ctx, search_query)

        combined_data = {
            "database_records": json.loads(db_data),
            "web_search_results": json.loads(web_data)
        }

        analysis = await self.generate_with_web_search(
            ctx=ctx,
            system_instruction=SYSTEM_INSTRUCTION,
            base_prompt=(
                f"Vendor: {company_name}\n"
                f"Country: {country}\n"
                f"License Data: {json.dumps(combined_data)}\n"
                "Verify licenses and certifications."
            ),
            schema=_LicenseAnalysis,
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
            raw_data=f"DB: {db_data}\nWEB: {web_data}",
            rationale=analysis.rationale,
        )

        if analysis.critical_license_revoked and analysis.license_details:
            result.anomaly = AnomalySignal(
                raised_by=self.step,
                reason=f"Critical License Revoked/Missing: {analysis.license_details}",
                severity=Severity.HIGH,
                suggested_revisit=[StepName.RESILIENCE, StepName.MEDIA], 
                new_context={"revoked_license": analysis.license_details},
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
    severity: SeverityLevel = Field(description="The severity level of the finding (INFO, LOW, MEDIUM, HIGH, CRITICAL).")
    is_red_flag: bool = Field(description="Set to true ONLY if the finding indicates a revoked, suspended, or missing critical license.")
    is_strength: bool = Field(default=False, description="Set to true if the finding indicates valid, active, and well-maintained licenses/certifications.")
    sources: list[_SourceModel] = Field(default_factory=list, description="The sources that support this finding.")

class _LicenseAnalysis(BaseModel):
    rationale: str = Field(description="Detailed explanation of your reasoning. MUST be generated first.")
    findings: list[_FindingModel] = Field(description="List of specific findings.")
    critical_license_revoked: bool = False
    license_details: str | None = None
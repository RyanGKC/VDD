# Know Your Business (KYB) Verification.

from __future__ import annotations

from agents.base_agent import BaseResearchAgent
from core.models import (
    AnomalySignal, DDContext, Finding, Severity, SeverityLevel, Source,
    StepName, StepResult, parse_severity,
)
from core.tools import verify_kyb_records

SYSTEM_INSTRUCTION = """
You are a KYB compliance officer. Verify the legal existence, active status, 
and corporate standing of the provided company. 

Return findings with severity. If the company is listed as inactive, dissolved, 
or operating under a fundamentally different legal entity than claimed, set 
'registration_invalid' to true and explain the 'invalid_reason'.

CRITICAL INSTRUCTION: If the company is a publicly traded corporation actively filing regulatory reports (e.g., with the SEC), consider its KYB status as 'Good Standing' and valid by default. Do not flag missing private registry fields as invalid registration.
"""

class KYBAgent(BaseResearchAgent):
    step = StepName.KYB

    async def research(self, ctx: DDContext) -> StepResult:
        company_name = ctx.company_details.company_name
        reg_id = ctx.company_details.registration_number

        data = await verify_kyb_records(ctx, company_name, reg_id)

        analysis = await self.generate_with_web_search(
            ctx=ctx,
            system_instruction=SYSTEM_INSTRUCTION,
            base_prompt=(
                f"Vendor: {company_name}\n"
                f"Registration ID: {reg_id}\n"
                f"Verification Data: {data}\n"
                "Assess KYB validity."
            ),
            schema=_KYBAnalysis,
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

        if analysis.registration_invalid and analysis.invalid_reason:
            result.anomaly = AnomalySignal(
                raised_by=self.step,
                reason=f"KYB Verification Failed: {analysis.invalid_reason}",
                severity=Severity.CRITICAL,
                suggested_revisit=[StepName.SHAREHOLDERS], 
                new_context={"kyb_failure_details": analysis.invalid_reason},
            )

        return result


# --- Inline response schema for Gemini --- #
from pydantic import BaseModel, Field  # noqa: E402

class _SourceModel(BaseModel):
    title: str = Field(description="The title of the source or document.")
    url: str | None = Field(default=None, description="The URL of the source, if available.")
    publisher: str | None = Field(default=None, description="The publisher or author of the source.")

class _FindingModel(BaseModel):
    summary: str = Field(description="A concise summary of the finding.")
    severity: SeverityLevel = Field(description="The severity level of the finding (INFO, LOW, MEDIUM, HIGH, CRITICAL).")
    is_red_flag: bool = Field(description="Set to true ONLY if the finding indicates the company is not in good standing, suspended, or illegitimate.")
    is_strength: bool = Field(default=False, description="Set to true if the finding indicates the company is well-established and in excellent standing.")
    sources: list[_SourceModel] = Field(default_factory=list, description="The sources that support this finding.")

class _KYBAnalysis(BaseModel):
    rationale: str = Field(description="Detailed explanation of your reasoning. MUST be generated first.")
    findings: list[_FindingModel] = Field(description="List of specific findings.")
    registration_invalid: bool = False
    invalid_reason: str | None = None
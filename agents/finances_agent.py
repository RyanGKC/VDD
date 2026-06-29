# Financial health & debt obligations.

from __future__ import annotations

import json
from agents.base_agent import BaseResearchAgent
from core.models import (
    AnomalySignal, DDContext, Finding, Severity, SeverityLevel, Source,
    StepName, StepResult, parse_severity,
)
from core.tools import fetch_financials, perform_web_search

SYSTEM_INSTRUCTION = """
You are a credit analyst. Assess the vendor's financial health, leverage,
liquidity, and debt obligations using both structured financial databases and
recent news/web searches. Flag solvency or going-concern risks. Cite each data source.

If you find evidence of significant debt owed to a party that was not 
previously disclosed, set 'undisclosed_related_party' to true and provide 
the 'related_party_name'.
"""

class FinancesAgent(BaseResearchAgent):
    step = StepName.FINANCES

    async def research(self, ctx: DDContext) -> StepResult:
        # Extract data using the updated CompanyDetails model
        company_name = ctx.company_details.company_name
        registration_id = ctx.company_details.registration_number

        # Hybrid approach: fetch DB financials and web search for debt news
        db_data = await fetch_financials(ctx, company_name, registration_id)
        search_query = f"{company_name} financial health debt obligations funding bankruptcy"
        web_data = await perform_web_search(ctx, search_query)
        
        combined_data = {
            "database_financials": json.loads(db_data),
            "web_news": json.loads(web_data)
        }
        
        analysis = await self.generate_with_web_search(
            ctx=ctx,
            system_instruction=SYSTEM_INSTRUCTION,
            base_prompt=f"Vendor: {company_name}\nFinancials: {json.dumps(combined_data)}",
            schema=_FinAnalysis,
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
        
        # Anomaly: undisclosed debt tied to a potentially sanctioned lender ->
        # revisit sanctions screening with that lender as a new entity.
        if analysis.undisclosed_related_party and analysis.related_party_name:
            result.anomaly = AnomalySignal(
                raised_by=self.step,
                reason=f"Undisclosed related-party debt counterparty found: {analysis.related_party_name}",
                severity=Severity.HIGH,
                suggested_revisit=[StepName.SANCTIONS, StepName.SHAREHOLDERS],
                new_context={
                    "additional_entities": [analysis.related_party_name]
                },
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
    is_red_flag: bool = Field(description="Set to true ONLY if the finding indicates severe financial distress, undisclosed debt, or solvency risks.")
    is_strength: bool = Field(default=False, description="Set to true if the finding indicates strong financial health or stability.")
    sources: list[_SourceModel] = Field(default_factory=list, description="The sources that support this finding.")

class _FinAnalysis(BaseModel):
    rationale: str = Field(description="Detailed explanation of your reasoning. MUST be generated first.")
    findings: list[_FindingModel] = Field(description="List of specific findings.")
    undisclosed_related_party: bool = Field(default=False, description="Set to true if you found evidence of undisclosed debt to a related party.")
    related_party_name: str | None = Field(default=None, description="The name of the related party, if undisclosed_related_party is true.")
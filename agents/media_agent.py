# Adverse Media and Reputation.

from __future__ import annotations

import json
from agents.base_agent import BaseResearchAgent
from core.models import (
    AnomalySignal, DDContext, Finding, Severity, SeverityLevel, Source,
    StepName, StepResult, parse_severity,
)
from core.tools import scan_adverse_media, perform_web_search

SYSTEM_INSTRUCTION = """
You are an adverse media screening analyst. Scan recent news and public 
records for negative coverage regarding the vendor or its executives using both 
adverse media databases and open web searches.

If you find critical breaking news (e.g., recent fraud indictment, executive 
arrests) that fundamentally changes the risk profile, set 'critical_breaking_news' 
to true and provide details.
"""

class MediaAgent(BaseResearchAgent):
    step = StepName.MEDIA

    async def research(self, ctx: DDContext) -> StepResult:
        company_name = ctx.company_details.company_name
        
        # Pull in new entities discovered from previous anomalies
        entities = [company_name] + ctx.enrichment.get("additional_entities", [])
        
        # Hybrid approach: Query media database AND search online news
        db_data = await scan_adverse_media(ctx, entities)
        search_query = f"{' OR '.join(entities)} news scandal controversy lawsuit investigation"
        web_data = await perform_web_search(ctx, search_query)

        combined_data = {
            "database_hits": json.loads(db_data),
            "web_search_results": json.loads(web_data)
        }

        analysis = await self.generate_with_web_search(
            ctx=ctx,
            system_instruction=SYSTEM_INSTRUCTION,
            base_prompt=(
                f"Entities to scan: {entities}\n"
                f"Media Data: {json.dumps(combined_data)}\n"
                "Assess adverse media and reputational risk."
            ),
            schema=_MediaAnalysis,
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

        if analysis.critical_breaking_news and analysis.news_details:
            result.anomaly = AnomalySignal(
                raised_by=self.step,
                reason=f"Critical Breaking News: {analysis.news_details}",
                severity=Severity.CRITICAL,
                suggested_revisit=[StepName.PROFILE, StepName.SANCTIONS], 
                new_context={"breaking_news": analysis.news_details},
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
    is_red_flag: bool = Field(description="Set to true ONLY if the finding indicates severe adverse media, fraud, or criminal allegations.")
    is_strength: bool = Field(default=False, description="Set to true if the finding indicates highly positive media coverage.")
    sources: list[_SourceModel] = Field(default_factory=list, description="The sources that support this finding.")

class _MediaAnalysis(BaseModel):
    rationale: str = Field(description="Detailed explanation of your reasoning. MUST be generated first.")
    findings: list[_FindingModel] = Field(description="List of specific findings.")
    critical_breaking_news: bool = False
    news_details: str | None = None
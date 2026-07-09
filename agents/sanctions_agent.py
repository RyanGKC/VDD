# Screens the vendor AND its known shareholders/UBOs against sanctions and
# watchlists. If it finds a sanctioned party that earlier steps didn't account 
# for, it raises an AnomalySignal asking the supervisor to revisit steps.

from __future__ import annotations

from agents.base_agent import BaseResearchAgent
from core.models import (
    AnomalySignal,
    DDContext,
    Finding,
    Severity,
    SeverityLevel,
    Source,
    StepName,
    StepResult,
    parse_severity,
)
from core.tools import screen_sanctions

# Schema we ask Gemini to fill.
SYSTEM_INSTRUCTION = """
You are a sanctions compliance analyst. Given a vendor, its shareholders,
and raw screening hits, assess sanctions exposure. Be conservative: flag
any plausible match for human review. Return findings with severity and
cite every screening source. If you identify a sanctioned or high-risk
party that is NOT present in the provided shareholder map, set
'requires_shareholder_review' to true and name the party.
"""


class SanctionsAgent(BaseResearchAgent):

    step = StepName.SANCTIONS

    @property
    def default_queries(self) -> list[str]:
        return [
            "{company} OFAC sanctions list",
            "{company} export control violations"
        ]

    async def research(self, ctx: DDContext) -> StepResult:
        # 1. Gather entities to screen: the vendor + any shareholders found
        #    by the upstream shareholders agent.
        shareholders_result = ctx.results.get(StepName.SHAREHOLDERS)
        shareholder_names = (
            shareholders_result.structured_data.get("shareholders", [])
            if shareholders_result
            else []
        )
        entities = [
            ctx.company_details.company_name,
            *(s.get("name") for s in shareholder_names),
        ]
        # Include anything an earlier anomaly injected (e.g. a new UBO).
        entities.extend(ctx.enrichment.get("additional_entities", []))

        # 2. Call the real screening tool (OpenSanctions, Dow Jones, etc.).
        raw_hits = await screen_sanctions(ctx, entities)

        # 3. Let Gemini reason over the hits and produce structured findings.
        analysis, url_map = await self.generate_with_web_search(
            ctx=ctx,
            system_instruction=SYSTEM_INSTRUCTION,
            base_prompt=(
                f"Vendor: {ctx.company_details.company_name}\n"
                f"Known shareholders: {shareholder_names}\n"
                f"Raw screening hits: {raw_hits}\n"
                "Assess sanctions exposure."
            ),
            schema=_SanctionsAnalysis,
        )

        # 4. Convert the LLM output into our standard StepResult (EXTRACTION OVER EVALUATION)
        findings = []
        for f in analysis.findings:
            # Deterministic override
            calc_severity = Severity.INFO
            calc_red_flag = False
            
            if f.is_on_sanctions_list and f.match_confidence_score > 0.90:
                calc_severity = Severity.CRITICAL
                calc_red_flag = True
            elif f.is_on_sanctions_list and f.match_confidence_score > 0.50:
                calc_severity = Severity.HIGH
                calc_red_flag = True
                
            findings.append(
                Finding(
                    summary=f.summary,
                    severity=calc_severity,
                    is_red_flag=calc_red_flag,
                    sources=[Source(title=s.title, url=url_map.get(s.source_id), publisher=s.publisher) for s in f.sources],
                )
            )

        result = StepResult(
            step=self.step,
            findings=findings,
            structured_data=analysis.model_dump(),
            sources=[s for f in findings for s in f.sources],
            raw_data=raw_hits,
            rationale=analysis.rationale,
        )

        # 5. Decide whether this requires re-planning.
        if analysis.requires_shareholder_review and analysis.new_party:
            result.anomaly = AnomalySignal(
                raised_by=self.step,
                reason=(
                    f"Sanctioned/high-risk party '{analysis.new_party}' "
                    "not present in original shareholder map."
                ),
                severity=Severity.CRITICAL,
                # Advisory hint: re-run the ownership-related steps.
                suggested_revisit=[
                    StepName.SHAREHOLDERS,
                    StepName.KYB,
                    StepName.SANCTIONS,
                ],
                new_context={"additional_entities": [analysis.new_party]},
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
    is_on_sanctions_list: bool = Field(description="Extract ONLY: Is the entity explicitly listed on a sanctions list? (true/false)")
    match_confidence_score: float = Field(description="Extract ONLY: The confidence score of the match from 0.0 to 1.0.")
    sources: list[_SourceModel] = Field(default_factory=list, description="The sources that support this finding.")


class _SanctionsAnalysis(BaseModel):
    rationale: str = Field(description="Detailed explanation of your reasoning. MUST be generated first.")
    findings: list[_FindingModel] = Field(description="List of specific findings.")
    has_sanctions: bool = Field(default=False, description="Set to true if there is a sanctions hit.")
    sanctioned_entity_names: list[str] = Field(default_factory=list, description="List of the specific sanctioned entity names.")
    requires_shareholder_review: bool = Field(default=False, description="Set to true if a sanctioned party was found that was NOT in the provided shareholder map.")
    new_party: str | None = Field(default=None, description="The name of the new high-risk party, if requires_shareholder_review is true.")

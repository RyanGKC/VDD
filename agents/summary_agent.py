"""
Synthesises all step results into the final DDReport: strengths, red flags,
an overall risk rating, recommendations, and a source list.

Includes a contradiction-detection pass that reviews all findings across
agents and removes or corrects conflicting statements before the final
report is generated.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from typing import Any
from core.openai_client import OpenAIClient
from core.models import (
    DDContext, DDReport, Finding, Severity, SeverityLevel,
    Source, StepName, parse_severity, SupplierItem
)

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """\
You are a due-diligence officer writing the final vendor risk
report. Given findings from all research areas, produce a concise executive
summary, an overall risk rating, and prioritised, actionable
recommendations. Ground every statement in the provided findings; do not
introduce new facts.
"""

CONTRADICTION_INSTRUCTION = """\
You are a senior quality-assurance reviewer for vendor due-diligence
reports. You will be given a numbered list of findings produced by
different research agents. Your job is to:

1. Identify any pairs of findings that are mutually exclusive logical contradictions of FACT (e.g. one says the company is privately held while another says it is publicly listed).
2. DO NOT flag differing opinions, mixed reviews, or contrasting perspectives as contradictions. For example, a finding stating the company is an "industry leader" does NOT contradict a finding that it "faces lawsuits for industry practices." Both are true and reflect multidimensional risk. You must retain both.
3. For genuine factual contradictions, decide which finding is more likely correct based on the strength of the cited sources and the specificity of the claim. 
4. Return the indices (0-based) of findings that should be REMOVED because they are the demonstrably false or weaker side of a factual contradiction.
5. Also return a brief explanation for each removal so the report can reference why a finding was excluded.

Be extremely conservative: only flag genuine logical contradictions of concrete facts. If in doubt, do not remove anything.
"""


class _SummaryModel(BaseModel):
    executive_summary: str
    recommendations: list[str]


class _ContradictionResult(BaseModel):
    removals: list[int] = Field(default_factory=list)
    explanations: list[str] = Field(default_factory=list)


# Map severity enum values to numeric risk scores (0–100 scale).
_SEVERITY_SCORES = {
    Severity.INFO: 0,
    Severity.LOW: 25,
    Severity.MEDIUM: 50,
    Severity.HIGH: 75,
    Severity.CRITICAL: 100,
}

# Friendly labels for radar chart axes keyed by StepName.
_STEP_LABELS = {
    StepName.SHAREHOLDERS: "Ownership",
    StepName.KYB: "KYB",
    StepName.SANCTIONS: "Sanctions",
    StepName.PROFILE: "Profile",
    StepName.LICENSES: "Licenses",
    StepName.FINANCES: "Financials",
    StepName.RESILIENCE: "Resilience",
    StepName.ESG: "ESG",
    StepName.MEDIA: "Media",
}


def _compute_step_risk_scores(findings: list[Finding]) -> dict[str, int]:
    """Derive a 0–100 risk score per step from cleaned findings."""
    scores: dict[str, int] = {label: 0 for label in _STEP_LABELS.values()}
    
    for f in findings:
        cat = getattr(f, "category", "Other")
        if f.is_red_flag:
            score = _SEVERITY_SCORES.get(f.severity, 0)
            if score > scores.get(cat, 0):
                scores[cat] = score

    return scores


class SummaryAgent:
    def __init__(self, client: Any) -> None:
        self.openai = client
        self.gemini = client

    async def _detect_contradictions(
        self, all_findings: list[Finding]
    ) -> list[int]:
        """Ask the LLM to identify contradictory findings and return
        the indices of the ones that should be removed."""
        if len(all_findings) < 2:
            return []

        numbered = "\n".join(
            f"[{i}] (severity={f.severity.value}, "
            f"is_strength={f.is_strength}, is_red_flag={f.is_red_flag}) "
            f"{f.summary}"
            for i, f in enumerate(all_findings)
        )

        try:
            from rag.rate_limiter import run_foreground_generation
            result = await run_foreground_generation(
                lambda: self.gemini.generate_structured(
                    system_instruction=CONTRADICTION_INSTRUCTION,
                    prompt=(
                        "Here are the findings to review:\n\n"
                        f"{numbered}\n\n"
                        "Identify contradictions and return the indices to remove."
                    ),
                    schema=_ContradictionResult,
                )
            )

            # Log what was removed for auditability
            for idx, explanation in zip(result.removals, result.explanations):
                if 0 <= idx < len(all_findings):
                    logger.info(
                        "Contradiction removed finding [%d]: %s — reason: %s",
                        idx, all_findings[idx].summary, explanation,
                    )

            return [i for i in result.removals if 0 <= i < len(all_findings)]

        except Exception:
            logger.exception("Contradiction detection failed; skipping")
            return []

    async def synthesise(self, ctx: DDContext) -> DDReport:
        # Flatten findings across every completed step.
        all_findings: list[Finding] = []
        raw_sources_by_step: dict[str, str] = {}
        for step_name, r in ctx.results.items():
            category_name = _STEP_LABELS.get(step_name, step_name.value)
            
            if r.raw_data:
                raw_sources_by_step[step_name.value] = r.raw_data
                
            for f in r.findings:
                f.category = category_name
                for s in f.sources:
                    title_lower = s.title.lower()
                    if not s.url or "registry" in title_lower or "database" in title_lower or "sec " in title_lower or "sanctions" in title_lower:
                        s.is_database = True
                all_findings.append(f)

        # --- Contradiction detection pass ---
        if hasattr(ctx, '_cached_contradiction_indices'):
            ctx.log("SUMMARY: Using speculative contradiction detection results from FlowEngine")
            removal_indices = ctx._cached_contradiction_indices
            all_findings = ctx._cached_all_findings
        else:
            ctx.log("SUMMARY: Running contradiction detection across all findings")
            removal_indices = await self._detect_contradictions(all_findings)

        if removal_indices:
            ctx.log(
                f"SUMMARY: Removed {len(removal_indices)} contradictory "
                f"finding(s): indices {removal_indices}"
            )
            cleaned_findings = [
                f for i, f in enumerate(all_findings)
                if i not in set(removal_indices)
            ]
        else:
            cleaned_findings = all_findings

        strengths = [f for f in cleaned_findings if f.is_strength]
        red_flags = [f for f in cleaned_findings if f.is_red_flag]

        # Deduplicate sources by URL/title for a clean references section.
        seen, sources = set(), []
        for r in ctx.results.values():
            for s in r.sources:
                key = s.url or s.title
                if key not in seen:
                    seen.add(key)
                    sources.append(s)

        # Compute real per-step risk scores from actual findings.
        step_risk_scores = _compute_step_risk_scores(cleaned_findings)

        # Programmatically determine overall risk
        if red_flags:
            max_score = max(_SEVERITY_SCORES.get(f.severity, 0) for f in red_flags)
            score_to_sev = {v: k for k, v in _SEVERITY_SCORES.items()}
            computed_risk = score_to_sev.get(max_score, Severity.LOW)
        else:
            computed_risk = Severity.LOW

        # Call Gemini asynchronously using the cleaned context
        try:
            from rag.rate_limiter import run_foreground_generation
            summary = await run_foreground_generation(
                lambda: self.gemini.generate_structured(
                    system_instruction=SYSTEM_INSTRUCTION,
                    prompt=(
                        f"Vendor: {ctx.company_details.company_name}\n"
                        f"Overall Risk (Must align summary with this): {computed_risk.value}\n"
                        f"Strengths: {[f.summary for f in strengths]}\n"
                        f"Red flags: "
                        f"{[(f.severity.value, f.summary) for f in red_flags]}\n"
                        f"Per-step risk scores: {step_risk_scores}\n"
                        f"Execution log (for context): {ctx.execution_log[-20:]}\n"
                        "Write the executive summary and recommendations."
                    ),
                    schema=_SummaryModel,
                )
            )
            exec_summary = summary.executive_summary
            recs = summary.recommendations
        except Exception as e:
            logger.exception(f"Synthesis failed for {ctx.company_details.company_name}")
            exec_summary = f"Synthesis failed: {e}. See audit log for raw findings."
            recs = []

        # Extract supply items from resilience structured data if available
        supply_items_data = []
        has_suppliers = True
        resilience_res = ctx.results.get(StepName.RESILIENCE)
        if resilience_res and resilience_res.structured_data:
            has_suppliers = resilience_res.structured_data.get("has_identifiable_third_party_suppliers", True)
            raw_items = resilience_res.structured_data.get("supply_items", [])
            for item in raw_items:
                if isinstance(item, dict):
                    supply_items_data.append(
                        SupplierItem(
                            supplier_name=item.get("supplier_name", ""),
                            category=item.get("category", ""),
                            description=item.get("description", "")
                        )
                    )

        return DDReport(
            vendor_name=ctx.company_details.company_name,
            overall_risk=computed_risk,
            strengths=strengths,
            red_flags=red_flags,
            recommendations=recs,
            sources=sources,
            executive_summary=exec_summary,
            step_risk_scores=step_risk_scores,
            raw_sources_by_step=raw_sources_by_step,
            supply_items=supply_items_data,
            has_identifiable_third_party_suppliers=has_suppliers,
        )
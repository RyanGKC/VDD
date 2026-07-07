import asyncio
import re
import logging
from ddgs import DDGS
from custom_tools.source_reliability import get_domain

logger = logging.getLogger(__name__)

# Domains known to be finance/company-info aggregators, not official sites —
# a company's own domain should never match these, so they're an instant disqualifier.
AGGREGATOR_BLOCKLIST = {
    "mykayaplus.com", "bloomberg.com", "reuters.com", "crunchbase.com",
    "linkedin.com", "wikipedia.org", "zoominfo.com", "opencorporates.com",
    "glassdoor.com", "indeed.com",
}

# Hand-maintained overrides for companies where automated resolution is likely
# ambiguous, or that recur often enough to be worth resolving once and reusing.
KNOWN_COMPANY_DOMAINS: dict[str, str] = {
    "malayan banking berhad": "maybank.com",
    "maybank": "maybank.com",
    # extend as VDD subjects recur
}


def _normalize(name: str) -> str:
    """Strip legal suffixes and punctuation for comparison."""
    name = name.lower()
    name = re.sub(r'\b(berhad|bhd|inc|llc|corp|corporation|ltd|limited|plc|nv|holdings?|group)\b', '', name)
    name = re.sub(r'[^a-z0-9]', '', name)
    return name


def _score_candidate(domain: str, company_name: str) -> int:
    """Higher score = more likely to be the real company domain."""
    if domain in AGGREGATOR_BLOCKLIST:
        return -100

    normalized_domain = re.sub(r'[^a-z0-9]', '', domain.split('.')[0].lower())
    normalized_name = _normalize(company_name)

    score = 0
    if normalized_name and (normalized_name in normalized_domain or normalized_domain in normalized_name):
        score += 50  # domain root contains the company name (or vice versa, for abbreviations)
    if domain.endswith((".com", ".com.my", ".co.uk", ".gov")):
        score += 5   # mild preference for common corporate TLDs
    # Penalize domains that look like blogs/subpages about the company rather than the company itself
    if any(kw in domain for kw in ("blog", "review", "wiki", "news")):
        score -= 20

    return score


async def resolve_company_website(company_name: str, num_candidates: int = 5) -> dict:
    """
    Returns {"domain": str | None, "confidence": "high"|"low"|"none", "candidates": [...]}
    instead of blindly trusting the first search result.
    """
    def _search():
        with DDGS() as ddgs:
            return list(ddgs.text(f"{company_name} official website", max_results=num_candidates, backend="auto"))

    try:
        results = await asyncio.to_thread(_search)
    except Exception as e:
        logger.warning(f"Website resolution search failed for {company_name}: {e}")
        return {"domain": None, "confidence": "none", "candidates": []}

    if not results:
        return {"domain": None, "confidence": "none", "candidates": []}

    scored = []
    for r in results:
        url = r.get("href")
        if not url:
            continue
        domain = get_domain(url)
        scored.append((domain, _score_candidate(domain, company_name), url))

    if not scored:
        return {"domain": None, "confidence": "none", "candidates": []}

    scored.sort(key=lambda x: x[1], reverse=True)
    top_domain, top_score, top_url = scored[0]

    confidence = "high" if top_score >= 50 else "low" if top_score > 0 else "none"

    return {
        "domain": top_domain if confidence != "none" else None,
        "confidence": confidence,
        "candidates": scored,  # kept for logging/debugging low-confidence cases
    }


async def resolve_company_website_with_overrides(company_name: str) -> dict:
    """Checks KNOWN_COMPANY_DOMAINS first, falls back to search-based resolution."""
    key = _normalize(company_name)
    for known_name, domain in KNOWN_COMPANY_DOMAINS.items():
        if _normalize(known_name) == key:
            return {"domain": domain, "confidence": "high", "candidates": [], "source": "override"}
    return await resolve_company_website(company_name)

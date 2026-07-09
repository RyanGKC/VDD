import logging
import time
import json
from pydantic import BaseModel
from urllib.parse import urlparse
from core.gemini_client import GeminiClient
from core.cache import PersistentCache

logger = logging.getLogger(__name__)
eval_cache = PersistentCache()

class DomainEvaluation(BaseModel):
    trust_level: str          # "high", "medium", "low"
    category: str             # "news_outlet", "government", "central_bank", "trade_press", "unknown", "suspicious"
    rationale: str            # one-line, for audit trail
    resembles_known_entity: bool  # flags potential impersonation of a well-known domain


SYSTEM_INSTRUCTION = (
    "You are evaluating whether a domain name likely belongs to a legitimate "
    "news outlet, government body, central bank, trade publication, or other "
    "established institution — based ONLY on the domain, URL path, TLD, and "
    "search result title/snippet provided below. You do NOT have access to the "
    "page's full content, and you must not assume anything about its editorial "
    "quality, awards, or citations beyond what these structural signals suggest.\n\n"
    "CRITICAL RULE: Rate paywalled market research and report-selling sites (e.g. ones that sell industry reports) as LOW trust. "
    "These are not useful because we cannot scrape their full content.\n\n"
    "Be especially suspicious of domains that closely resemble well-known "
    "institutions but aren't exact matches (e.g. 'bbc-news-uk.com' instead of "
    "'bbc.com', 'reuters-daily.com' instead of 'reuters.com', "
    "'centralbank-gov.com' instead of an actual central bank domain) — this "
    "pattern is commonly used to impersonate trusted sources and should be "
    "rated LOW trust specifically because of the resemblance, not high trust."
)


CACHE_TTL_SECONDS = 60 * 60 * 24 * 60  # 60 days

async def evaluate_domain(url: str, title: str, snippet: str) -> DomainEvaluation:
    parsed = urlparse(url)
    domain = parsed.netloc.lower().removeprefix("www.")

    cached = eval_cache.get(f"domain_eval:{domain}")
    if cached:
        try:
            payload = json.loads(cached)
            if "cached_at" in payload and "evaluation" in payload:
                if time.time() - payload.get("cached_at", 0) < CACHE_TTL_SECONDS:
                    return DomainEvaluation.model_validate(payload["evaluation"])
            else:
                return DomainEvaluation.model_validate(payload)
        except Exception:
            pass

    try:
        gemini = GeminiClient(model="gemini-2.5-flash-lite")
        prompt = (
            f"Domain: {domain}\n"
            f"Full URL: {url}\n"
            f"Search result title: {title}\n"
            f"Search result snippet: {snippet}\n\n"
            "Evaluate this domain's trustworthiness as a source for a financial/"
            "regulatory due diligence report."
        )
        result = await gemini.generate_structured(
            system_instruction=SYSTEM_INSTRUCTION,
            prompt=prompt,
            schema=DomainEvaluation
        )
        if result.resembles_known_entity and result.trust_level.lower() != "low":
            logger.warning(f"Overriding trust_level to low for likely-impersonation domain: {domain}")
            result = result.model_copy(update={"trust_level": "low"})
            
        payload = {
            "cached_at": time.time(),
            "evaluation": result.model_dump()
        }
        eval_cache.set(f"domain_eval:{domain}", json.dumps(payload))
        
        return result
    except Exception as e:
        logger.warning(f"Domain evaluation failed for {domain}: {e}")
        # Fail closed — treat evaluation failure as low trust rather than defaulting to acceptance
        return DomainEvaluation(trust_level="low", category="unknown", rationale=f"Evaluation error: {e}", resembles_known_entity=False)

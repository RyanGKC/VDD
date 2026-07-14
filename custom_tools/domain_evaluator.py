import logging
import time
import json
import asyncio
from pydantic import BaseModel
from urllib.parse import urlparse
from core.gemini_client import GeminiClient
from core.cache import PersistentCache

logger = logging.getLogger(__name__)
eval_cache = PersistentCache()

class DomainEvaluation(BaseModel):
    domain: str              # explicit identifier, not positional
    trust_level: str          # "high", "medium", "low"
    category: str             # "news_outlet", "government", "central_bank", "trade_press", "unknown", "suspicious"
    rationale: str            # one-line, for audit trail
    resembles_known_entity: bool  # flags potential impersonation of a well-known domain

class BatchDomainEvaluation(BaseModel):
    evaluations: list[DomainEvaluation]

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
    "rated LOW trust specifically because of the resemblance, not high trust.\n\n"
    "IMPORTANT: Return the exact domain string provided back in each evaluation object's 'domain' field."
)

CACHE_TTL_SECONDS = 60 * 60 * 24 * 60  # 60 days
CHUNK_SIZE = 12

def chunk_items(items: list, size: int = CHUNK_SIZE) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]

def reconcile_batch(input_domains: list[str], evaluations: list[DomainEvaluation]) -> dict[str, DomainEvaluation]:
    by_domain = {e.domain: e for e in evaluations}
    missing = set(input_domains) - set(by_domain.keys())
    extra = set(by_domain.keys()) - set(input_domains)

    if missing or extra:
        logger.warning(
            f"Batch stitching mismatch — missing: {missing}, unexpected: {extra}"
        )
        # extra/unrecognized entries are discarded, never silently applied
    return by_domain

def apply_impersonation_override(evaluations: dict[str, DomainEvaluation]) -> dict[str, DomainEvaluation]:
    for domain, evaluation in evaluations.items():
        if evaluation.resembles_known_entity and evaluation.trust_level != "low":
            logger.info(f"Impersonation override applied: {domain}")
            evaluation.trust_level = "low"
    return evaluations

async def cache_batch_results(evaluations: dict[str, DomainEvaluation]):
    for domain, evaluation in evaluations.items():
        payload = {
            "cached_at": time.time(),
            "evaluation": evaluation.model_dump()
        }
        eval_cache.set(f"domain_eval:{domain}", json.dumps(payload))

async def evaluate_domain_batch(chunk: list[dict]) -> list[DomainEvaluation]:
    if not chunk:
        return []
    
    input_domains = [item["domain"] for item in chunk]
    
    prompt = "Evaluate the following domains:\n\n"
    for item in chunk:
        prompt += f"--- Domain ---\nDomain: {item['domain']}\nFull URL: {item.get('href', '')}\nTitle: {item.get('title', '')}\nSnippet: {item.get('body', '')}\n\n"
        
    gemini = GeminiClient(model="gemini-2.5-flash-lite")
    
    try:
        response = await gemini.generate_structured(
            system_instruction=SYSTEM_INSTRUCTION,
            prompt=prompt,
            schema=BatchDomainEvaluation,
        )
        reconciled = reconcile_batch(input_domains, response.evaluations)
        reconciled = apply_impersonation_override(reconciled)
    except Exception as e:
        logger.warning(f"Batch domain evaluation failed for chunk: {e}")
        reconciled = {
            domain: DomainEvaluation(
                domain=domain, trust_level="low", category="unknown",
                rationale="fallback: batch call failed", resembles_known_entity=False,
            )
            for domain in input_domains
        }
        
    # Fill in missing domains with fallbacks
    final_results = []
    for domain in input_domains:
        if domain in reconciled:
            final_results.append(reconciled[domain])
        else:
            final_results.append(DomainEvaluation(
                domain=domain, trust_level="low", category="unknown",
                rationale="fallback: batch stitching dropped domain", resembles_known_entity=False,
            ))
            
    return final_results

async def batch_evaluate_domains(snippets_data: list[dict]) -> dict[str, DomainEvaluation]:
    # Check cache first
    cached_results = {}
    uncached_chunks = []
    
    for item in snippets_data:
        url = item.get("href", "")
        parsed = urlparse(url)
        domain = parsed.netloc.lower().removeprefix("www.")
        item["domain"] = domain
        
        cached = eval_cache.get(f"domain_eval:{domain}")
        if cached:
            try:
                payload = json.loads(cached)
                if "cached_at" in payload and "evaluation" in payload:
                    if time.time() - payload.get("cached_at", 0) < CACHE_TTL_SECONDS:
                        eval_obj = DomainEvaluation.model_validate(payload["evaluation"])
                        if not eval_obj.domain:
                            eval_obj.domain = domain
                        cached_results[domain] = eval_obj
                        continue
                else:
                    eval_obj = DomainEvaluation.model_validate(payload)
                    if not eval_obj.domain:
                        eval_obj.domain = domain
                    cached_results[domain] = eval_obj
                    continue
            except Exception:
                pass
                
        uncached_chunks.append(item)
        
    # Deduplicate uncached to avoid duplicate batch calls for the same domain
    unique_uncached = {}
    for item in uncached_chunks:
        if item["domain"] not in unique_uncached:
            unique_uncached[item["domain"]] = item
            
    uncached_list = list(unique_uncached.values())
    chunks = chunk_items(uncached_list, CHUNK_SIZE)
    
    # Run batch evaluation for uncached domains
    batch_results_nested = await asyncio.gather(*[evaluate_domain_batch(c) for c in chunks])
    
    newly_evaluated = {}
    for chunk_res in batch_results_nested:
        for evaluation in chunk_res:
            newly_evaluated[evaluation.domain] = evaluation
            
    # Cache newly evaluated
    await cache_batch_results(newly_evaluated)
    
    # Combine results
    cached_results.update(newly_evaluated)
    
    return cached_results

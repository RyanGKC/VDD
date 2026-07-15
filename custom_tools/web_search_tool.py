import logging
import asyncio
import io
from pypdf import PdfReader
from curl_cffi import requests as cffi_requests
import time
import re
from collections import defaultdict
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any, List
from ddgs import DDGS
from pydantic import BaseModel

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.gemini_client import GeminiClient
from custom_tools.source_reliability import check_tier, get_domain
from custom_tools.domain_evaluator import batch_evaluate_domains, eval_cache
from custom_tools.query_expansion import expand_query
from custom_tools.relevance_scorer import batch_score_all_relevance
from core.retry import retry_async
import json

logger = logging.getLogger(__name__)

import trafilatura
import ftfy
import re

def _parse_html(html_content: str) -> Optional[str]:
    """Synchronous CPU-bound parsing of HTML."""
    # 0. Prevent `<noscript>` pollution (even in successfully rendered SPAs)
    import re
    html_content = re.sub(r'<noscript.*?</noscript>', '', html_content, flags=re.DOTALL | re.IGNORECASE)

    # 1. Try trafilatura first
    extracted_text = trafilatura.extract(
        html_content,
        include_comments=False,
        include_tables=True,
        no_fallback=False
    )
    
    # 2. Fallback to BeautifulSoup if trafilatura fails
    if not extracted_text:
        soup = BeautifulSoup(html_content, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        lines = (line.strip() for line in text.splitlines())
        extracted_text = "\n".join(line for line in lines if line)

    # 3. Cleanup with ftfy + regex normalization
    if extracted_text:
        clean_text = ftfy.fix_text(extracted_text)
        
        # Strip lines and remove completely empty ones or standalone list markers
        lines = [line.strip() for line in clean_text.splitlines()]
        cleaned_lines = []
        for line in lines:
            if not line:
                continue
            # Remove isolated punctuation often left over from broken HTML lists
            if line in ("-", "•", "*", "▪", "●", "—"):
                continue
            cleaned_lines.append(line)
        
        clean_text = "\n".join(cleaned_lines)
        clean_text = re.sub(r'[ \t]+', ' ', clean_text)
        return clean_text.strip()
    return ""

import os
from playwright.async_api import async_playwright, Browser, Playwright, TimeoutError as PlaywrightTimeoutError

PLAYWRIGHT_ESCALATION_ENABLED = os.getenv("PLAYWRIGHT_ESCALATION_ENABLED", "false").lower() == "true"
MAX_CONCURRENT_CONTEXTS = int(os.getenv("PLAYWRIGHT_MAX_CONTEXTS", "4"))

_playwright: Playwright | None = None
_browser: Browser | None = None
_browser_lock = asyncio.Lock()
_browser_context_sem = asyncio.Semaphore(MAX_CONCURRENT_CONTEXTS)

async def get_browser() -> Browser:
    global _playwright, _browser
    async with _browser_lock:
        if not _browser or not _browser.is_connected():
            if _browser:
                await _browser.close()
            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(headless=True)
    return _browser

async def shutdown_browser():
    global _browser, _playwright
    if _browser:
        await _browser.close()
        _browser = None
    if _playwright:
        await _playwright.stop()
        _playwright = None

BOT_WALL_MARKERS = (
    "enable javascript", 
    "javascript must be enabled", 
    "javascript is disabled",
    "checking your browser", 
    "attention required",
    "just a moment", 
    "captcha", 
    "access denied",
)
MIN_VIABLE_BODY_LENGTH = 500

def _should_escalate_to_playwright(status_code: int | None, body_text: str | None, exc: Exception | None, is_pdf: bool) -> bool:
    if is_pdf:
        return False
    if exc is not None:
        return True
    if status_code in (403, 429, 503):
        return True
    if body_text is not None and len(body_text) < MIN_VIABLE_BODY_LENGTH:
        return True
    if body_text is not None and any(m in body_text.lower() for m in BOT_WALL_MARKERS):
        return True
    return False

async def _fetch_via_playwright(url: str, timeout: int = 15) -> str | None:
    try:
        browser = await get_browser()
    except Exception as e:
        logger.warning(f"Failed to get browser: {e}")
        return None

    async with _browser_context_sem:
        try:
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        except Exception as e:
            logger.warning(f"Playwright context creation failed for {url}: {e}")
            return None
            
        try:
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except PlaywrightTimeoutError:
                pass
            html_content = await page.content()
            return await asyncio.to_thread(_parse_html, html_content)
        except Exception as e:
            logger.warning(f"Playwright escalation failed for {url}: {e}")
            return None
        finally:
            await context.close()

async def _fetch_via_curl_cffi(url: str, session: cffi_requests.AsyncSession, timeout: int):
    status_code, body_text, is_pdf = None, None, False
    try:
        resp = await retry_async(session.get, url, allow_redirects=True, timeout=timeout)
        status_code = resp.status_code
        if status_code != 200:
            resp.raise_for_status()
            
        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > 10 * 1024 * 1024:
            logger.warning(f"File too large, skipped: {url} ({content_length} bytes)")
            return status_code, "__PDF_ERROR__: File exceeded 10MB limit", None, True
        
        content_type = resp.headers.get("Content-Type", "").lower()
        if "application/pdf" in content_type or url.lower().endswith(".pdf"):
            is_pdf = True
            def _parse_pdf(pdf_bytes: bytes) -> str:
                try:
                    reader = PdfReader(io.BytesIO(pdf_bytes))
                    if reader.is_encrypted:
                        return "__PDF_ERROR__: PDF is encrypted"
                    text_pages = [page.extract_text() for page in reader.pages if page.extract_text()]
                    return "\n".join(text_pages)
                except Exception as e:
                    logger.warning(f"Failed to parse PDF {url}: {e}")
                    return f"__PDF_ERROR__: PDF format error - {e}"
            
            extracted_text = await asyncio.to_thread(_parse_pdf, resp.content)
            return status_code, extracted_text.strip(), None, True
        else:
            body_text = resp.text
            return status_code, body_text, None, False
            
    except Exception as e:
        return status_code, body_text, e, is_pdf

async def fetch_and_clean_html(url: str, session: cffi_requests.AsyncSession, timeout: int = 15) -> Optional[str]:
    """Fetches a URL and extracts clean text from HTML or PDF."""
    status_code, body_text, exc, is_pdf = await _fetch_via_curl_cffi(url, session, timeout)

    if not _should_escalate_to_playwright(status_code, body_text, exc, is_pdf):
        if exc or not body_text:
            if exc:
                logger.warning(f"Failed to fetch {url}: {exc}")
            return body_text if is_pdf else None
        
        # If it's a PDF, body_text already contains the extracted text. If it's HTML, we need to parse it.
        if is_pdf:
            return body_text
            
        return await asyncio.to_thread(_parse_html, body_text)

    if not PLAYWRIGHT_ESCALATION_ENABLED:
        logger.info(f"Would escalate {url} to Playwright (disabled by flag)")
        if exc or not body_text:
            if exc:
                logger.warning(f"Failed to fetch {url}: {exc}")
            return body_text if is_pdf else None
        return await asyncio.to_thread(_parse_html, body_text)

    logger.info(f"Escalating {url} to Playwright — status={status_code}, exc={exc}")
    result = await _fetch_via_playwright(url, timeout)
    if result is not None:
        return result
        
    # Playwright also failed, fallback to whatever curl_cffi got
    if exc or not body_text:
        return body_text if is_pdf else None
    return await asyncio.to_thread(_parse_html, body_text)


class SummaryResult(BaseModel):
    summary: str

class SearchResultItem(BaseModel):
    title: str
    source_url: str
    content: str
    relevance_score: int
    trust_tier: str

class WebSearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]
    error: Optional[str] = None
    debug_stats: dict | None = None

async def summarize_text(text: str) -> str:
    """Summarizes a long webpage using Gemini."""
    try:
        gemini = GeminiClient(model="gemini-2.5-flash-lite")
        system_instruction = "You are a web scraper assistant. Summarize the following webpage text. Extract all concrete facts, numbers, dates, and claims. Omit boilerplate."
        
        prompt = f"Webpage Text:\n\n{text}"
        
        result = await gemini.generate_structured(
            system_instruction=system_instruction,
            prompt=prompt,
            schema=SummaryResult
        )
        return result.summary
    except Exception as e:
        logger.error(f"Failed to summarize text: {e}")
        return f"[Summarization Failed: {e}]"


async def search_web(query: str, max_results: int = 3, company_domain: str | None = None, debug: bool = False) -> str:
    """
    A custom tool for AI agents to search the web using DuckDuckGo and scrape the results.
    Returns a strict JSON string matching WebSearchResponse.
    """
    try:
        results, stats = await _orchestrate_search(query, max_results, company_domain)
        response = WebSearchResponse(query=query, results=[SearchResultItem(**r) for r in results], debug_stats=stats if debug else None)
        return response.model_dump_json()
    except Exception as e:
        logger.error(f"Search failed for '{query}': {e}")
        return WebSearchResponse(query=query, results=[], error=str(e)).model_dump_json()

async def _orchestrate_search(query: str, max_results: int = 3, company_domain: str | None = None) -> tuple[list[dict], dict]:
    start_time = time.time()
    logger.info(f"Running resilient web search for: '{query}'")
    
    stats = {
        "query_variants_used": 0,
        "websites_searched": 0,
        "allowlist_hits": 0,
        "blocklist_hits": 0,
        "domain_evaluated_accepted": 0,
        "domain_evaluated_rejected": 0,
        "reliable_sites_dropped_due_to_errors": 0,
        "reliable_sites_in_output": 0,
        "total_runtime_seconds": 0.0,
        "phase_seconds": {
            "dynamic_list_load": 0.0,
            "initial_ddg_search": 0.0,
            "adaptive_expansion": 0.0,
            "embedding_batch": 0.0,
            "llm_fanout": 0.0,
            "fetch_and_summarize": 0.0,
        },
        "adaptive_expansion_triggered": False,
        "candidates_before_cap": 0,
        "candidates_after_cap": 0
    }
    
    try:
        t0_dyn = time.time()
        # Load dynamic lists from cache
        dynamic_allow = set()
        dynamic_block = set()
        CACHE_TTL_SECONDS = 60 * 60 * 24 * 60
        for key, val_json in eval_cache.get_by_prefix("domain_eval:"):
            try:
                data = json.loads(val_json)
                domain = key.split("domain_eval:")[1]
                
                if "evaluation" in data and "cached_at" in data:
                    if time.time() - data.get("cached_at", 0) > CACHE_TTL_SECONDS:
                        continue
                    data = data["evaluation"]
                
                trust_lvl = str(data.get("trust_level", "")).lower()
                if trust_lvl in ("high", "medium"):
                    dynamic_allow.add(domain)
                elif trust_lvl == "low":
                    dynamic_block.add(domain)
            except Exception:
                pass
        
        stats["phase_seconds"]["dynamic_list_load"] = time.time() - t0_dyn

        def _cheap_prerank_score(q: str, title: str, snippet: str) -> int:
            q_words = set(q.lower().split())
            text = f"{title} {snippet}".lower()
            return sum(1 for w in q_words if w in text)
            
        async def _search_and_merge(variants: list[str]) -> list[dict]:
            search_pool_size = min(100, max(30, max_results * 10))

            # DDG rate-limits concurrent bursts from the same IP. Firing all variants
            # simultaneously with a long timeout + escalating backoff (the old settings)
            # doesn't avoid the rate limit — it just waits it out silently, which is why
            # this phase measured ~85s in production instead of the ~12s a single search takes.
            # Fix: stagger launch times so most variants never trigger the burst limiter in
            # the first place, and keep the per-attempt timeout/retry short so that if one
            # variant does get throttled anyway, we drop it fast instead of waiting ~90s for it.
            DDG_TIMEOUT_SECONDS = 15       # was 30 — comfortably above the ~11.5s observed baseline for one successful call
            DDG_MAX_ATTEMPTS = 2           # was 3 — one retry as a safety net, not a patience mechanism
            DDG_RETRY_DELAY_SECONDS = 2    # was escalating 1s/2s — flat delay, we're not trying to outlast the limiter
            STAGGER_SECONDS = 1.0          # spacing between concurrent variant launches to avoid a correlated burst

            def _do_search(q: str) -> List[Dict[str, str]]:
                for attempt in range(DDG_MAX_ATTEMPTS):
                    try:
                        with DDGS(timeout=DDG_TIMEOUT_SECONDS) as ddgs:
                            return list(ddgs.text(q, max_results=search_pool_size, backend="auto"))
                    except Exception as e:
                        if attempt == DDG_MAX_ATTEMPTS - 1:
                            logger.warning(f"DDG search failed for variant '{q}' after {DDG_MAX_ATTEMPTS} attempts: {e}")
                            raise e
                        time.sleep(DDG_RETRY_DELAY_SECONDS)

            async def _staggered_search(q: str, delay: float) -> List[Dict[str, str]]:
                if delay:
                    await asyncio.sleep(delay)
                return await asyncio.to_thread(_do_search, q)

            search_tasks = [
                asyncio.create_task(_staggered_search(q, i * STAGGER_SECONDS))
                for i, q in enumerate(variants)
            ]
            results_per_variant = await asyncio.gather(*search_tasks, return_exceptions=True)
            
            merged = []
            for variant_results in results_per_variant:
                if isinstance(variant_results, Exception):
                    logger.warning(f"A query variant search failed: {variant_results}")
                    continue
                for res in variant_results:
                    merged.append(res)
            return merged

        def _bucket_by_tier(snippets: list[dict], seen: set[str]):
            allow = []
            unknown = []
            for res in snippets:
                url = res.get("href")
                if not url or url in seen:
                    continue
                seen.add(url)
                
                tier = check_tier(url, company_domain=company_domain, dynamic_allow=dynamic_allow, dynamic_block=dynamic_block)
                if tier == "allow":
                    allow.append(res)
                    stats["allowlist_hits"] += 1
                    print(f"✅ [CUSTOM] Allowed known reliable source: {url}")
                elif tier == "block":
                    logger.info(f"Dropping blocklisted source: {url} (domain: {get_domain(url)})")
                    stats["blocklist_hits"] += 1
                    print(f"🚫 [CUSTOM] Dropped blocklisted source: {url}")
                else:
                    unknown.append(res)
            return allow, unknown

        seen_urls = set()
        
        # Opt 1: Fire query expansion concurrently with the first DDG search
        expansion_task = asyncio.create_task(expand_query(query))
        t0_ddg = time.time()
        search_snippets = await _search_and_merge([query])
        stats["phase_seconds"]["initial_ddg_search"] = time.time() - t0_ddg
        stats["query_variants_used"] = 1
        
        allowed_snippets, unknown_snippets = _bucket_by_tier(search_snippets, seen_urls)
        
        # Adaptive expansion: if we don't have enough good candidates, use the pre-fetched expansion
        if len(allowed_snippets) < max_results * 2:
            t0_adapt = time.time()
            variants = await expansion_task
            stats["query_variants_used"] += len(variants) - 1 # excluding original
            extra_snippets = await _search_and_merge(variants[1:]) # skip original
            
            extra_allow, extra_unknown = _bucket_by_tier(extra_snippets, seen_urls)
            allowed_snippets.extend(extra_allow)
            unknown_snippets.extend(extra_unknown)
            stats["phase_seconds"]["adaptive_expansion"] = time.time() - t0_adapt
            stats["adaptive_expansion_triggered"] = True
        else:
            expansion_task.cancel()
            
        stats["websites_searched"] = len(seen_urls)
        
        # Cap candidates before LLM fan-out
        stats["candidates_before_cap"] = len(allowed_snippets) + len(unknown_snippets)
        CANDIDATE_CAP = max(20, max_results * 4)
        
        allowed_snippets.sort(key=lambda r: _cheap_prerank_score(query, r.get("title", ""), r.get("body", "")), reverse=True)
        allowed_snippets = allowed_snippets[:CANDIDATE_CAP]
        
        unknown_snippets.sort(key=lambda r: _cheap_prerank_score(query, r.get("title", ""), r.get("body", "")), reverse=True)
        unknown_snippets = unknown_snippets[:CANDIDATE_CAP]
        stats["candidates_after_cap"] = len(allowed_snippets) + len(unknown_snippets)

        # Opt 3: Pre-compute query embedding + all snippet embeddings in batched API calls
        gemini = GeminiClient(model="gemini-2.5-flash-lite")
        
        # Build texts for all snippets we might score (allowed now + unknowns that may be promoted)
        all_candidate_snippets = allowed_snippets + unknown_snippets
        snippet_texts = [f"{r.get('title', '')} {r.get('body', '')}" for r in all_candidate_snippets]
        
        # Single batched embed call: [query] + all snippet texts
        t0_emb = time.time()
        all_embeddings = await gemini.embed_content([query] + snippet_texts)
        stats["phase_seconds"]["embedding_batch"] = time.time() - t0_emb
        query_emb = all_embeddings[0]
        snippet_embedding_map = {}
        for idx, res in enumerate(all_candidate_snippets):
            url = res.get("href", "")
            snippet_embedding_map[url] = all_embeddings[1 + idx]

        # Fire both fan-outs concurrently
        t0_fanout = time.time()
        
        eval_task = asyncio.create_task(batch_evaluate_domains(unknown_snippets)) if unknown_snippets else None
        
        if eval_task:
            eval_results = await eval_task
            newly_accepted = []
            for res in unknown_snippets:
                url = res.get("href", "")
                from urllib.parse import urlparse
                domain = urlparse(url).netloc.lower().removeprefix("www.")
                evaluation = eval_results.get(domain)
                if not evaluation:
                    continue
                
                trust_lvl = str(evaluation.trust_level).lower()
                res["trust_tier"] = trust_lvl
                if trust_lvl in ("high", "medium"):
                    newly_accepted.append(res)
                    dynamic_allow.add(domain)
                    stats["domain_evaluated_accepted"] += 1
                    logger.info(
                        f"Accepted evaluated domain: {domain} "
                        f"(trust: {trust_lvl}, category: {evaluation.category})"
                    )
                    print(f"🤔 [CUSTOM] Evaluated unknown domain '{domain}': ACCEPTED (Trust: {trust_lvl})")
                else:
                    dynamic_block.add(domain)
                    stats["domain_evaluated_rejected"] += 1
                    logger.info(
                        f"Rejected evaluated domain: {domain} "
                        f"(trust: {trust_lvl}, rationale: {evaluation.rationale})"
                    )
                    print(f"🛑 [CUSTOM] Evaluated unknown domain '{domain}': REJECTED (Trust: {trust_lvl})")
            
            allowed_snippets.extend(newly_accepted)

        # Now score all allowed snippets at once
        pre_scored = []
        if allowed_snippets:
            relevance_scores = await batch_score_all_relevance(
                query, 
                allowed_snippets, 
                query_emb, 
                snippet_embedding_map
            )
            for res, relevance in zip(allowed_snippets, relevance_scores):
                res["relevance_score"] = relevance.score
                pre_scored.append((res, relevance))

        stats["phase_seconds"]["llm_fanout"] = time.time() - t0_fanout
        scored_snippets = []
        for res, relevance in pre_scored:
            scored_snippets.append((res, relevance.score))
            logger.info(f"Relevance {relevance.score} for {res.get('href')}: {relevance.reason}")

        scored_snippets.sort(key=lambda x: x[1], reverse=True)
        allowed_snippets = [res for res, _ in scored_snippets]
        enriched_results = []
        # Opt 6: Dynamic batch size so a single batch covers the target
        BATCH_SIZE = max_results + 2
        
        domain_semaphores = defaultdict(lambda: asyncio.Semaphore(2))
        
        t0_fetch = time.time()
        # Create a single shared session for connection pooling across the search
        async with cffi_requests.AsyncSession(impersonate="chrome") as session:
            for i in range(0, len(allowed_snippets), BATCH_SIZE):
                batch = allowed_snippets[i:i+BATCH_SIZE]
                
                async def process_snippet(res):
                    url = res.get("href")
                    domain = get_domain(url)
                    
                    async with domain_semaphores[domain]:
                        raw_text = await fetch_and_clean_html(url, session)
                        
                    if not raw_text:
                        print(f"❌ [CUSTOM] Failed to extract text from {url}")
                        return None
                    elif raw_text.startswith("__PDF_ERROR__"):
                        print(f"❌ [CUSTOM] PDF extraction failed for {url} ({raw_text})")
                        return None
                    
                    # Opt 5: Removed dead truncated_content computation
                    summarized_content = await summarize_text(raw_text)
                    print(f"📝 [CUSTOM] Successfully extracted and summarized: {url}")
                    
                    return {
                        "title": res.get("title", ""),
                        "source_url": url,
                        "content": summarized_content,
                        "relevance_score": res.get("relevance_score", 0),
                        "trust_tier": res.get("trust_tier", "allow")
                    }
                    
                # Execute batch concurrently using as_completed for early exit
                tasks = [asyncio.create_task(process_snippet(res)) for res in batch]
                for coro in asyncio.as_completed(tasks):
                    r = await coro
                    if r is not None:
                        enriched_results.append(r)
                        if len(enriched_results) >= max_results:
                            # Cancel remaining tasks to free up resources
                            for task in tasks:
                                if not task.done():
                                    task.cancel()
                            await asyncio.gather(*tasks, return_exceptions=True)
                            break
                    else:
                        stats["reliable_sites_dropped_due_to_errors"] += 1
                        
                if len(enriched_results) >= max_results:
                    break
                    
            stats["reliable_sites_in_output"] = len(enriched_results)
            stats["total_runtime_seconds"] = round(time.time() - start_time, 2)
            stats["phase_seconds"]["fetch_and_summarize"] = time.time() - t0_fetch
            
        logger.info(f"[timing] '{query}' -> {json.dumps(stats)}")
        return enriched_results, stats
        
    except Exception as e:
        logger.error(f"Orchestration failed for '{query}': {e}")
        raise e

if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    
    async def test():
        query = "Apple Strategy and Business Model"
        
        print("\n=== Testing Search Web Pipeline ===")
        results = await search_web(query, max_results=10)
        print(json.dumps(results, indent=2))
        
    asyncio.run(test())

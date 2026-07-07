import logging
import asyncio
import io
from pypdf import PdfReader
from curl_cffi import requests as cffi_requests
import time
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any, List
from ddgs import DDGS
from pydantic import BaseModel

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.gemini_client import GeminiClient
from custom_tools.source_reliability import check_tier, get_domain
from custom_tools.domain_evaluator import evaluate_domain, eval_cache
from custom_tools.query_expansion import expand_query
from custom_tools.relevance_scorer import score_relevance
import json

logger = logging.getLogger(__name__)

import trafilatura
import ftfy
import re

def _parse_html(html_content: str) -> Optional[str]:
    """Synchronous CPU-bound parsing of HTML."""
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
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
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

async def fetch_and_clean_html(url: str, session: cffi_requests.AsyncSession, timeout: int = 10) -> Optional[str]:
    """Fetches a URL and extracts clean text from HTML or PDF."""
    try:
        resp = await session.get(url, allow_redirects=True, timeout=timeout)
        if resp.status_code != 200:
            resp.raise_for_status()
        
        content_type = resp.headers.get("Content-Type", "").lower()
        
        if "application/pdf" in content_type or url.lower().endswith(".pdf"):
            def _parse_pdf(pdf_bytes: bytes) -> str:
                try:
                    reader = PdfReader(io.BytesIO(pdf_bytes))
                    text_pages = [page.extract_text() for page in reader.pages if page.extract_text()]
                    return "\n".join(text_pages)
                except Exception as e:
                    logger.warning(f"Failed to parse PDF {url}: {e}")
                    return ""
            
            extracted_text = await asyncio.to_thread(_parse_pdf, resp.content)
            return extracted_text.strip()
        else:
            html_content = resp.text
            
            # Offload the CPU-bound HTML parsing to a background thread
            extracted_text = await asyncio.to_thread(_parse_html, html_content)
            return extracted_text
            
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None

class SummaryResult(BaseModel):
    summary: str

async def summarize_text(text: str) -> str:
    """Summarizes a long webpage using Gemini."""
    try:
        gemini = GeminiClient(model="gemini-2.5-flash-lite")
        system_instruction = "You are a web scraper assistant. Summarize the following webpage text. Extract all concrete facts, numbers, dates, and claims. Omit boilerplate."
        
        # We don't want to blow up the model's token limit either, so we still truncate to a reasonable max size (e.g., 30k chars) before summarizing
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

def flatten_text(text: str) -> str:
    """Collapses newlines into a single space, for human-readable flat output."""
    flat = re.sub(r'\s*\n\s*', ' ', text)
    flat = re.sub(r'[ \t]+', ' ', flat)
    return flat.strip()

async def search_web(query: str, max_results: int = 3, company_domain: str | None = None) -> Dict[str, Any]:
    """
    A custom tool for AI agents to search the web using DuckDuckGo and scrape the results.
    Returns both truncated and summarized content for each result.
    """
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
        "total_runtime_seconds": 0.0
    }
    
    try:
        # Load dynamic lists from cache
        dynamic_allow = set()
        dynamic_block = set()
        for key, val_json in eval_cache.get_by_prefix("domain_eval:"):
            try:
                data = json.loads(val_json)
                domain = key.split("domain_eval:")[1]
                trust_lvl = str(data.get("trust_level", "")).lower()
                if trust_lvl in ("high", "medium"):
                    dynamic_allow.add(domain)
                elif trust_lvl == "low":
                    dynamic_block.add(domain)
            except Exception:
                pass

        query_variants = await expand_query(query)
        stats["query_variants_used"] = len(query_variants)

        def _do_search(q: str) -> List[Dict[str, str]]:
            with DDGS() as ddgs:
                return list(ddgs.text(q, max_results=100, backend="auto"))

        search_tasks = [asyncio.to_thread(_do_search, q) for q in query_variants]
        results_per_variant = await asyncio.gather(*search_tasks, return_exceptions=True)

        # Merge and dedupe by URL, preserving first-seen order
        seen_urls = set()
        search_snippets = []
        for variant_results in results_per_variant:
            if isinstance(variant_results, Exception):
                logger.warning(f"A query variant search failed: {variant_results}")
                continue
            for res in variant_results:
                url = res.get("href")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    search_snippets.append(res)

        logger.info(f"Merged {len(search_snippets)} unique results across {len(query_variants)} query variants")
        stats["websites_searched"] = len(search_snippets)
        
        allowed_snippets = []
        for res in search_snippets:
            url = res.get("href")
            if not url:
                continue
        
            tier = check_tier(url, company_domain=company_domain, dynamic_allow=dynamic_allow, dynamic_block=dynamic_block)
        
            if tier == "allow":
                allowed_snippets.append(res)
                stats["allowlist_hits"] += 1
                print(f"✅ [CUSTOM] Allowed known reliable source: {url}")
        
            elif tier == "block":
                logger.info(f"Dropping blocklisted source: {url} (domain: {get_domain(url)})")
                stats["blocklist_hits"] += 1
                print(f"🚫 [CUSTOM] Dropped blocklisted source: {url}")
        
            else:  # unknown — evaluate before accepting
                evaluation = await evaluate_domain(
                    url=url,
                    title=res.get("title", ""),
                    snippet=res.get("body", "")
                )
                domain = get_domain(url)
                trust_lvl = str(evaluation.trust_level).lower()
                if trust_lvl in ("high", "medium"):
                    allowed_snippets.append(res)
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

        # NEW: score relevance for trust-cleared candidates, then sort
        scored_snippets = []
        for res in allowed_snippets:
            relevance = await score_relevance(
                query=query,  # score against the ORIGINAL query, not the variant that found it
                title=res.get("title", ""),
                snippet=res.get("body", "")
            )
            scored_snippets.append((res, relevance.score))
            logger.info(f"Relevance {relevance.score} for {res.get('href')}: {relevance.reason}")

        scored_snippets.sort(key=lambda x: x[1], reverse=True)
        allowed_snippets = [res for res, _ in scored_snippets]
        enriched_results = []
        BATCH_SIZE = 5
        
        # Create a single shared session for connection pooling across the search
        async with cffi_requests.AsyncSession(impersonate="chrome") as session:
            for i in range(0, len(allowed_snippets), BATCH_SIZE):
                batch = allowed_snippets[i:i+BATCH_SIZE]
                
                async def process_snippet(res):
                    url = res.get("href")
                    raw_text = await fetch_and_clean_html(url, session)
                    if not raw_text:
                        print(f"❌ [CUSTOM] Failed to extract text from {url}")
                        return None
                        
                    flat_text = flatten_text(raw_text)
                    truncated_content = flat_text[:5000] + ("..." if len(flat_text) > 5000 else "")
                    summarized_content = await summarize_text(raw_text)
                    print(f"📝 [CUSTOM] Successfully extracted and summarized: {url}")
                    
                    return {
                        "title": res.get("title", ""),
                        "url": url,
                        "snippet": res.get("body", ""),
                        "truncated_content": truncated_content,
                        "summarized_content": summarized_content
                    }
                    
                # Execute batch concurrently using as_completed for early exit
                tasks = [process_snippet(res) for res in batch]
                for coro in asyncio.as_completed(tasks):
                    r = await coro
                    if r is not None:
                        enriched_results.append(r)
                        if len(enriched_results) >= max_results:
                            # Cancel remaining tasks to free up resources
                            for task in tasks:
                                if isinstance(task, asyncio.Task) and not task.done():
                                    task.cancel()
                            break
                    else:
                        stats["reliable_sites_dropped_due_to_errors"] += 1
                        
                if len(enriched_results) >= max_results:
                    break
                    
            stats["reliable_sites_in_output"] = len(enriched_results)
            stats["total_runtime_seconds"] = round(time.time() - start_time, 2)
            
        return {
            "query": query,
            "results": enriched_results,
            "run_statistics": stats
        }
        
    except Exception as e:
        logger.error(f"Search failed for '{query}': {e}")
        stats["total_runtime_seconds"] = round(time.time() - start_time, 2)
        return {
            "query": query,
            "error": str(e),
            "results": [],
            "run_statistics": stats
        }

if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    
    async def test():
        query = "Apple Strategy and Business Model"
        
        print("\n=== Testing Search Web Pipeline ===")
        results = await search_web(query, max_results=10)
        print(json.dumps(results, indent=2))
        
    asyncio.run(test())

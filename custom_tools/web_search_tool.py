import logging
import asyncio
import httpx
import time
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any, List
from ddgs import DDGS
from pydantic import BaseModel

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.gemini_client import GeminiClient
from custom_tools.source_reliability import is_reliable, get_domain

logger = logging.getLogger(__name__)

import trafilatura
import ftfy
import re

async def fetch_and_clean_html(url: str, timeout: int = 10) -> Optional[str]:
    """Fetches a URL and extracts clean text from HTML."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # We use a standard browser user-agent to avoid basic bot blocks
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            resp = await client.get(url, headers=headers, follow_redirects=True)
            resp.raise_for_status()
            
            html_content = resp.text
            
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

async def search_web(query: str, max_results: int = 3) -> Dict[str, Any]:
    """
    A custom tool for AI agents to search the web using DuckDuckGo and scrape the results.
    Returns both truncated and summarized content for each result.
    """
    start_time = time.time()
    logger.info(f"Running resilient web search for: '{query}'")
    
    stats = {
        "websites_searched": 0,
        "unreliable_sites": 0,
        "reliable_sites": 0,
        "reliable_sites_dropped_due_to_errors": 0,
        "reliable_sites_in_output": 0,
        "total_runtime_seconds": 0.0
    }
    
    try:
        def _do_search() -> List[Dict[str, str]]:
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=100, backend="auto"))
                
        search_snippets = await asyncio.to_thread(_do_search)
        logger.info(f"DDG returned {len(search_snippets)} snippets")
        stats["websites_searched"] = len(search_snippets)
        
        enriched_results = []
        
        for res in search_snippets:
            if len(enriched_results) >= max_results:
                break
                
            url = res.get("href")
            if not url or not is_reliable(url):
                if url:
                    logger.info(f"Dropping unreliable source: {url} (domain: {get_domain(url)})")
                    stats["unreliable_sites"] += 1
                continue
                
            stats["reliable_sites"] += 1
                
            # Attempt scrape
            raw_text = await fetch_and_clean_html(url)
            if raw_text is None:
                logger.info(f"Skipping {url} due to scrape failure, trying next source.")
                stats["reliable_sites_dropped_due_to_errors"] += 1
                continue
                
            # 1. Truncation
            flat_text = flatten_text(raw_text)
            truncated_content = flat_text[:5000] + ("..." if len(flat_text) > 5000 else "")
            
            # 2. Summarization
            summarized_content = await summarize_text(raw_text)
                
            enriched_results.append({
                "title": res.get("title", ""),
                "url": url,
                "snippet": res.get("body", ""),
                "truncated_content": truncated_content,
                "summarized_content": summarized_content
            })
            
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

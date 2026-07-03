import httpx
from bs4 import BeautifulSoup
import trafilatura

async def ddg_search(query: str, num_results: int = 5) -> list[dict]:
    import asyncio
    from ddgs import DDGS

    def _do_search():
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=num_results, backend="duckduckgo"))

    try:
        raw_results = await asyncio.to_thread(_do_search)
        results = []
        for r in raw_results:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", "")
            })
        return results
    except Exception as e:
        print(f"DDG Search error: {e}")
        return []

async def fetch_page_json(url: str) -> dict:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        try:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
        except httpx.HTTPError as e:
            return {"url": url, "error": str(e), "content": None}

    extracted = trafilatura.extract(
        resp.text,
        include_comments=False,
        include_tables=True,
        output_format="json"  # trafilatura can emit structured JSON directly
    )
    if not extracted:
        return {"url": url, "error": "extraction_failed", "content": None}

    import json
    data = json.loads(extracted)
    return {
        "url": url,
        "title": data.get("title"),
        "date": data.get("date"),
        "content": data.get("text", "")[:8000],
        "error": None
    }

async def web_search_and_read(query: str, num_results: int = 3) -> list[dict]:
    results = await ddg_search(query, num_results)
    pages = []
    for r in results:
        page = await fetch_page_json(r["url"])
        page["search_title"] = r["title"]
        page["search_snippet"] = r["snippet"]
        pages.append(page)
    return pages

if __name__ == "__main__":
    import asyncio
    import json
    
    async def test():
        query = "Apple Inc corporate structure and executive leadership"
        print(f"Testing web_search_and_read with query: '{query}'\n")
        results = await web_search_and_read(query, num_results=1)
        print(json.dumps(results))
        
    asyncio.run(test())
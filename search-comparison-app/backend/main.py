import asyncio
import os
import sys
from pathlib import Path

# Add the root VDD Prototype directory to sys.path so we can import custom_tools
root_dir = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(root_dir))

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx
from dotenv import load_dotenv

# Import the existing custom scraper tool
from custom_tools.web_search_tool import search_web

# Load environment variables
load_dotenv(root_dir / ".env")

app = FastAPI(title="Search Comparison API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def get_exa_results(query: str, max_results: int = 5) -> list[dict]:
    api_key = os.getenv("EXA_API_KEY")
    if not api_key:
        return [{"title": "Error", "snippet": "EXA_API_KEY not found in .env", "url": ""}]
        
    payload = {
        "query": query,
        "type": "auto",
        "numResults": max_results,
        "contents": {"highlights": True}
    }
    
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    
    try:
        print(f"🔄 [EXA] Initiating Exa API call for: '{query}'")
        async with httpx.AsyncClient() as client:
            resp = await client.post("https://api.exa.ai/search", json=payload, headers=headers)
            
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for res in data.get("results", []):
                    highlights = res.get("highlights", [])
                    snippet = " ".join(highlights) if highlights else "No snippet available."
                    results.append({
                        "title": res.get("title", "No Title"),
                        "snippet": snippet,
                        "url": res.get("url", "")
                    })
                print(f"✅ [EXA] Exa search completed for '{query}'. Found {len(results)} results.")
                return results
            else:
                print(f"❌ [EXA] Exa API returned error {resp.status_code}: {resp.text}")
                return [{"title": f"Exa Error {resp.status_code}", "snippet": resp.text, "url": ""}]
    except Exception as e:
        print(f"❌ [EXA] Exception during Exa search: {e}")
        return [{"title": "Exception", "snippet": str(e), "url": ""}]

@app.get("/api/compare")
async def compare_search(query: str = Query(..., description="The search query")):
    """Runs Exa and Custom Search concurrently and returns both sets of results."""
    
    # Run both searches concurrently
    print(f"\n🚀 [API] Received comparison request for query: '{query}'")
    print(f"🔄 [CUSTOM] Initiating Custom Web Scraper for: '{query}'")
    
    exa_task = get_exa_results(query, max_results=5)
    custom_task = search_web(query, max_results=5)
    
    exa_results, custom_raw = await asyncio.gather(exa_task, custom_task)
    
    print(f"✅ [CUSTOM] Custom Web Scraper completed for: '{query}'. Found {len(custom_raw.get('results', []))} results.")
    print(f"✨ [API] Comparison request completed successfully for: '{query}'\n")
    
    # Format custom results to match the structure
    custom_formatted = []
    for res in custom_raw.get("results", []):
        custom_formatted.append({
            "title": res.get("title", "Unknown"),
            "url": res.get("url", ""),
            "snippet": res.get("truncated_content", "")[:800] + ("..." if len(res.get("truncated_content", "")) > 800 else ""),
            "summary": res.get("summarized_content", "")
        })
        
    return {
        "query": query,
        "exa": exa_results,
        "custom": custom_formatted
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8002, reload=True)

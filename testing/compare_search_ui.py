import asyncio
import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import json
import httpx
from dotenv import load_dotenv
from custom_tools.web_search_tool import search_web

# Load environment variables
load_dotenv(".env")

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
                return results
            else:
                return [{"title": f"Exa Error {resp.status_code}", "snippet": resp.text, "url": ""}]
    except Exception as e:
        return [{"title": "Exception", "snippet": str(e), "url": ""}]

def generate_html(query: str, exa_results: list[dict], custom_results: list[dict], output_path: str):
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Search Engine Comparison</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #f9fafb; color: #111827; margin: 0; padding: 20px; }}
            .header {{ text-align: center; margin-bottom: 30px; }}
            .query-badge {{ background: #e5e7eb; padding: 5px 15px; border-radius: 20px; font-weight: 600; }}
            .container {{ display: flex; gap: 20px; }}
            .column {{ flex: 1; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
            h2 {{ margin-top: 0; padding-bottom: 10px; border-bottom: 2px solid #e5e7eb; }}
            .result-card {{ border: 1px solid #e5e7eb; border-radius: 6px; padding: 15px; margin-bottom: 15px; }}
            .result-title {{ font-size: 1.1em; font-weight: 600; margin-bottom: 5px; color: #2563eb; text-decoration: none; display: block; }}
            .result-title:hover {{ text-decoration: underline; }}
            .result-url {{ font-size: 0.85em; color: #10b981; margin-bottom: 10px; word-break: break-all; }}
            .result-snippet {{ font-size: 0.95em; line-height: 1.5; color: #4b5563; }}
            .summary-box {{ margin-top: 10px; padding: 10px; background: #f3f4f6; border-radius: 4px; border-left: 4px solid #8b5cf6; font-size: 0.9em; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Search Pipeline Comparison</h1>
            <p>Query: <span class="query-badge">{query}</span></p>
        </div>
        
        <div class="container">
            <!-- EXA COLUMN -->
            <div class="column">
                <h2>Exa API Results</h2>
    """
    
    for res in exa_results:
        html += f"""
                <div class="result-card">
                    <a href="{res['url']}" target="_blank" class="result-title">{res['title']}</a>
                    <div class="result-url">{res['url']}</div>
                    <div class="result-snippet">{res['snippet']}</div>
                </div>
        """
        
    html += """
            </div>
            
            <!-- CUSTOM COLUMN -->
            <div class="column">
                <h2>Custom Scraper Results</h2>
    """
    
    for res in custom_results:
        summary = res.get('summarized_content', '')
        # Only show the first 800 chars of truncated content to match exa's snippet sizes roughly for ui, 
        # but keep the LLM summary box
        snippet = res.get('truncated_content', '')[:800] + "..."
        
        html += f"""
                <div class="result-card">
                    <a href="{res.get('url', '#')}" target="_blank" class="result-title">{res.get('title', 'Unknown')}</a>
                    <div class="result-url">{res.get('url', '')}</div>
                    <div class="result-snippet">{snippet}</div>
        """
        if summary and not summary.startswith("[Summarization Failed"):
            html += f"""
                    <div class="summary-box">
                        <strong>LLM Summary:</strong> {summary}
                    </div>
            """
        html += """
                </div>
        """
        
    html += """
            </div>
        </div>
    </body>
    </html>
    """
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
        
    print(f"Comparison HTML successfully generated at: {output_path}")

async def main():
    query = "Malayan Banking Berhad regulatory licenses certifications"
    output_html = os.path.join(os.path.dirname(__file__), "search_comparison.html")
    
    print(f"Executing Exa search for: '{query}'...")
    exa_results = await get_exa_results(query, max_results=3)
    
    print(f"Executing Custom search for: '{query}'...")
    custom_raw = await search_web(query, max_results=3)
    custom_results = custom_raw.get("results", [])
    
    generate_html(query, exa_results, custom_results, output_html)

if __name__ == "__main__":
    asyncio.run(main())

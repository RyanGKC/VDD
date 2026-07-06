import os
import json
import asyncio
import httpx
from datetime import datetime
from typing import Any
import re
import urllib.parse
from core.models import DDContext
from core.cache import PersistentCache
import logging
from pydantic import BaseModel, Field
from core.gemini_client import GeminiClient
from core.dependencies import http_client
from custom_tools.yfinance_tool import get_financial_statement

logger = logging.getLogger(__name__)

cache_db = PersistentCache()

# Helper to load cached doc or fetch
async def fetch_json(ctx: DDContext, url: str, headers: dict = None, auth=None) -> dict | None:
    cached = cache_db.get(url)
    if cached:
        return json.loads(cached)
    
    try:
        resp = await http_client.get(url, headers=headers, auth=auth)
        if resp.status_code == 200:
            data = resp.json()
            cache_db.set(url, json.dumps(data))
            return data
    except Exception as e:
        print(f"Error fetching {url}: {e}")
    return None

async def fetch_text(ctx: DDContext, url: str, headers: dict = None, auth=None) -> str | None:
    cached = cache_db.get(url)
    if cached:
        return cached
    
    try:
        resp = await http_client.get(url, headers=headers, auth=auth)
        if resp.status_code == 200:
            text = resp.text
            cache_db.set(url, text)
            return text
    except Exception as e:
        print(f"Error fetching {url}: {e}")
    return None

async def resolve_company(ctx: DDContext, company_name: str, country: str | None) -> None:
    if not country:
        return
    
    country_upper = country.upper()
    
    # Resolve US CIK
    if country_upper in ("US", "USA") and not ctx.company_details.cik:
        url = "https://www.sec.gov/files/company_tickers.json"
        headers = {"User-Agent": "VDD_Prototype/1.0 (contact@example.com)"}
        data = await fetch_json(ctx, url, headers=headers)
        if data:
            search_name = company_name.lower().replace(" ", "").replace(",", "").replace(".", "")
            for entry in data.values():
                title = entry["title"].lower().replace(" ", "").replace(",", "").replace(".", "")
                if title == search_name or search_name in title:
                    ctx.company_details.cik = str(entry["cik_str"]).zfill(10)
                    break

    # Resolve UK Company Number
    elif country_upper in ("UK", "GB", "GBR") and not ctx.company_details.company_number:
        api_key = os.getenv("COMPANIES_HOUSE_API_KEY")
        if api_key:
            url = f"https://api.company-information.service.gov.uk/search/companies?q={company_name}"
            data = await fetch_json(ctx, url, auth=(api_key, ""))
            if data and data.get("items"):
                ctx.company_details.company_number = data["items"][0].get("company_number")

async def fetch_corporate_registry(ctx: DDContext, company_name: str, country: str | None) -> str:
    await resolve_company(ctx, company_name, country)
    result = {"quality_flag": "partial", "source": "API", "data": {}}
    
    if company_name == "Tech Corp Risk" and ctx.use_mock:
        result["data"]["corporate_structure"] = "Wholly owned subsidiary of Tech Corp Global Holdings"
        result["quality_flag"] = "high"
        return json.dumps(result)
    
    if country and country.upper() in ("US", "USA"):
        cik = ctx.company_details.cik
        if cik:
            url = f"https://data.sec.gov/submissions/CIK{cik}.json"
            headers = {"User-Agent": "VDD_Prototype/1.0 (contact@example.com)"}
            data = await fetch_json(ctx, url, headers=headers)
            if data:
                result["quality_flag"] = "high"
                result["data"]["entity_type"] = "Publicly Traded Corporation"
                result["data"]["ubo_expectation"] = "Dispersed/Institutional"
                
                # Filter filings to only ownership-relevant forms
                recent = data.get("filings", {}).get("recent", {})
                relevant_forms = {"10-K", "10-K/A", "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A", "DEF 14A"}
                forms = recent.get("form", [])
                filtered = {k: [] for k in recent.keys()}
                count = 0
                for i, form in enumerate(forms):
                    if form in relevant_forms and count < 5:
                        for k in recent.keys():
                            if i < len(recent[k]):
                                filtered[k].append(recent[k][i])
                        count += 1
                result["data"]["sec_filings"] = filtered
        else:
            result["error"] = f"CIK not resolved for query: name='{company_name}', country='{country}'"
    
    elif country and country.upper() in ("UK", "GB", "GBR"):
        cnum = ctx.company_details.company_number
        api_key = os.getenv("COMPANIES_HOUSE_API_KEY")
        if cnum and api_key:
            url = f"https://api.company-information.service.gov.uk/company/{cnum}/persons-with-significant-control"
            data = await fetch_json(ctx, url, auth=(api_key, ""))
            if data:
                result["quality_flag"] = "high"
                result["data"]["psc_register"] = data.get("items", [])
        else:
            result["error"] = f"Company number or API key missing for query: name='{company_name}'"
            
    return json.dumps(result)

async def verify_kyb_records(ctx: DDContext, company_name: str, reg_id: str | None) -> str:
    await resolve_company(ctx, company_name, ctx.company_details.country)
    result = {"quality_flag": "partial", "source": "API", "data": {}}
    country = ctx.company_details.country
    
    if country and country.upper() in ("US", "USA"):
        cik = ctx.company_details.cik
        if cik:
            url = f"https://data.sec.gov/submissions/CIK{cik}.json"
            headers = {"User-Agent": "VDD_Prototype/1.0 (contact@example.com)"}
            data = await fetch_json(ctx, url, headers=headers)
            if data:
                result["quality_flag"] = "high"
                result["data"]["entity_type"] = "Publicly Traded Corporation"
                result["data"]["company_info"] = {
                    "name": data.get("name"),
                    "sic": data.get("sicDescription"),
                    "stateOfIncorporation": data.get("stateOfIncorporation")
                }
        else:
            result["error"] = f"CIK not resolved for query: name='{company_name}', country='{country}'"
            
    elif country and country.upper() in ("UK", "GB", "GBR"):
        cnum = ctx.company_details.company_number
        api_key = os.getenv("COMPANIES_HOUSE_API_KEY")
        if cnum and api_key:
            url_profile = f"https://api.company-information.service.gov.uk/company/{cnum}"
            url_officers = f"https://api.company-information.service.gov.uk/company/{cnum}/officers"
            profile = await fetch_json(ctx, url_profile, auth=(api_key, ""))
            officers = await fetch_json(ctx, url_officers, auth=(api_key, ""))
            if profile:
                result["quality_flag"] = "high"
                result["data"]["profile"] = profile
                result["data"]["officers"] = officers.get("items", []) if officers else []
        else:
            result["error"] = f"Company number or API key missing for query: name='{company_name}'"
            
    return json.dumps(result)

async def screen_sanctions(ctx: DDContext, entities: list[str]) -> str:
    result = {"quality_flag": "partial", "source": "API", "hits": []}
    api_key = os.getenv("OPENSANCTIONS_API_KEY")
    
    if api_key and entities:
        payload = {
            "queries": {
                f"q_{i}": {"schema": "LegalEntity", "properties": {"name": [name]}} 
                for i, name in enumerate(entities)
            }
        }
        
        # Build composite key and check cache
        cache_key = f"https://api.opensanctions.org/match/default|{json.dumps(payload, sort_keys=True)}"
        cached = cache_db.get(cache_key)
        if cached:
            return cached

        try:
            headers = {"Authorization": f"ApiKey {api_key}"}
            resp = await http_client.post("https://api.opensanctions.org/match/default", json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                result["quality_flag"] = "high"
                for qid, qres in data.get("responses", {}).items():
                    for match in qres.get("results", []):
                        result["hits"].append({
                            "entity": match.get("id"),
                            "caption": match.get("caption"),
                            "score": match.get("score")
                        })
                final_str = json.dumps(result)
                cache_db.set(cache_key, final_str)
                return final_str
            else:
                logger.warning(f"OpenSanctions API returned status code {resp.status_code}. Initiating web search fallback.")
        except Exception as e:
            logger.warning(f"OpenSanctions API error: {e}. Initiating web search fallback.")
            
    # Web search fallback for real mode
    if entities:
        logger.info("OpenSanctions API unavailable or failed. Executing fallback web search sanctions screening.")
        result["source"] = "web_search_fallback"
        result["quality_flag"] = "medium"
        result["web_search_results"] = {}
        
        for entity in entities:
            query = f'"{entity}" sanctioned OFAC list PEP'
            try:
                search_res = await perform_web_search(ctx, query)
                result["web_search_results"][entity] = json.loads(search_res)
            except Exception as se:
                result["web_search_results"][entity] = {"error": str(se)}
                
        return json.dumps(result)

    # Mock local cache fallback if no entities
    result["local_cache_status"] = "OFAC, UN, HMT checked (simulated cached)"
    return json.dumps(result)

async def verify_licenses(ctx: DDContext, company_name: str, country: str | None) -> str:
    result = {"quality_flag": "partial", "source": "API", "data": {}}
    if country and country.upper() in ("US", "USA"):
        result["data"]["sam_gov"] = "Partial data - SAM API requires setup"
    elif country and country.upper() in ("UK", "GB", "GBR"):
        result["data"]["fca_register"] = "Partial data - FCA API requires setup"
    return json.dumps(result)

async def fetch_financials(ctx: DDContext, company_name: str, registration_id: str | None) -> str:
    await resolve_company(ctx, company_name, ctx.company_details.country)
    result = {"quality_flag": "partial", "source": "API", "data": {}}
    country = ctx.company_details.country
    
    provider = os.getenv("FINANCIAL_DATA_PROVIDER", "fmp").lower()
    
    if provider == "yfinance":
        # Sanitize company name to improve Yahoo Finance search accuracy
        # Yahoo Finance is fragile with exact suffixes like "Holdings N.V."
        clean_name = re.sub(r'(?i)\b(inc|llc|corp|corporation|ltd|limited|plc|nv|n\.v\.|holdings?|group|ag|sa|ab|spa)(?:\b|\.|$)', '', company_name)
        # Remove trailing punctuation or whitespace
        clean_name = re.sub(r'[,\.\s]+', ' ', clean_name).strip()
        search_query = clean_name if clean_name else company_name
        search_query = urllib.parse.quote(search_query)

        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={search_query}"
        try:
            from curl_cffi import requests as cffi_requests
            # Use curl_cffi to bypass Yahoo's strict TLS/User-Agent blocks
            resp = await asyncio.to_thread(
                cffi_requests.get,
                url,
                impersonate="chrome",
                timeout=10
            )
            search_data = resp.json() if resp.status_code == 200 else None
        except Exception as e:
            logger.error(f"Failed to search yfinance for {search_query}: {e}")
            search_data = None
        
        ticker = None
        if search_data and search_data.get("quotes"):
            ticker = search_data["quotes"][0].get("symbol")
            
        if ticker:
            logger.info(f"Resolved ticker {ticker} for {company_name}")
            income_statement = await asyncio.to_thread(get_financial_statement, ticker, "income")
            
            if "data_markdown" in income_statement:
                result["quality_flag"] = "high"
                result["source"] = "yfinance"
                result["data"]["yfinance_income"] = income_statement["data_markdown"]
            else:
                result["data"]["yfinance_error"] = income_statement.get("error", "Unknown error")
        else:
            result["data"]["yfinance_error"] = f"Could not resolve ticker for {company_name}"
            
    else:
        # FMP / SEC fallback logic
        fmp_key = os.getenv("FMP_API_KEY")
        if country and country.upper() in ("US", "USA"):
            cik = ctx.company_details.cik
            if cik:
                url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
                headers = {"User-Agent": "VDD_Prototype/1.0 (contact@example.com)"}
                data = await fetch_json(ctx, url, headers=headers)
                if data:
                    result["quality_flag"] = "high"
                    result["data"]["xbrl_facts"] = "Available (Truncated for brevity)"
            elif fmp_key:
                url = f"https://financialmodelingprep.com/api/v3/income-statement/{company_name}?apikey={fmp_key}"
                data = await fetch_json(ctx, url)
                if data:
                    result["quality_flag"] = "medium"
                    result["data"]["fmp_income"] = data[:3]
                    
        elif country and country.upper() in ("UK", "GB", "GBR"):
            if fmp_key:
                url = f"https://financialmodelingprep.com/api/v3/income-statement/{company_name}?apikey={fmp_key}"
                data = await fetch_json(ctx, url)
                if data:
                    result["quality_flag"] = "high"
                    result["data"]["fmp_income"] = data[:3]
                    
    return json.dumps(result)

async def scan_adverse_media(ctx: DDContext, entities: list[str]) -> str:
    result = {"quality_flag": "partial", "source": "API", "articles": []}
    news_key = os.getenv("NEWSAPI_KEY")
    
    if news_key and entities:
        query = " OR ".join([f'"{e}"' for e in entities])
        url = f"https://newsapi.org/v2/everything?q={query}&apiKey={news_key}"
        try:
            data = await fetch_json(ctx, url)
            if data and data.get("status") == "ok":
                result["quality_flag"] = "high"
                result["articles"] = [
                    {"headline": a["title"], "source": a["source"]["name"], "date": a["publishedAt"]}
                    for a in data.get("articles", [])[:5]
                ]
        except Exception as e:
            result["error"] = str(e)
            
    return json.dumps(result)

class SearchResultSnippet(BaseModel):
    title: str
    snippet: str
    url: str

class WebSearchResponse(BaseModel):
    search_results: list[SearchResultSnippet] = Field(description="A list of search results found on the internet")

async def perform_web_search(ctx: DDContext, query: str) -> str:
    result = {"quality_flag": "partial", "source": "Unknown", "search_results": []}
    provider = os.getenv("SEARCH_PROVIDER", "exa").lower()
    
    async def _try_exa():
        exa_api_key = os.getenv("EXA_API_KEY")
        if not exa_api_key:
            return None
        exa_payload = {
            "query": query,
            "type": "auto",
            "numResults": 5,
            "contents": {"highlights": True}
        }
        exa_cache_key = f"https://api.exa.ai/search|{json.dumps(exa_payload, sort_keys=True)}"
        cached = cache_db.get(exa_cache_key)
        if cached:
            return cached
            
        try:
            headers = {"x-api-key": exa_api_key, "Content-Type": "application/json"}
            resp = await http_client.post("https://api.exa.ai/search", json=exa_payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                res_obj = {"source": "Exa API", "quality_flag": "high", "search_results": []}
                for res in data.get("results", []):
                    highlights = res.get("highlights", [])
                    snippet = " ".join(highlights) if highlights else "No snippet available."
                    res_obj["search_results"].append({
                        "title": res.get("title", ""),
                        "snippet": snippet,
                        "url": res.get("url", "")
                    })
                final_str = json.dumps(res_obj)
                cache_db.set(exa_cache_key, final_str)
                return final_str
            else:
                logger.warning(f"Exa API failed: {resp.status_code}")
        except Exception as e:
            logger.warning(f"Exa API exception: {str(e)}")
        return None

    async def _try_tavily():
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            return None
        payload = {
            "api_key": api_key, "query": query, "search_depth": "basic",
            "include_answer": False, "max_results": 5
        }
        cache_payload = {k: v for k, v in payload.items() if k != "api_key"}
        cache_key = f"https://api.tavily.com/search|{json.dumps(cache_payload, sort_keys=True)}"
        cached = cache_db.get(cache_key)
        if cached:
            return cached

        try:
            resp = await http_client.post("https://api.tavily.com/search", json=payload)
            if resp.status_code == 200:
                data = resp.json()
                res_obj = {"source": "Tavily", "quality_flag": "high", "search_results": []}
                res_obj["search_results"] = [
                    {"title": res.get("title"), "snippet": res.get("content"), "url": res.get("url")}
                    for res in data.get("results", [])
                ]
                final_str = json.dumps(res_obj)
                cache_db.set(cache_key, final_str)
                return final_str
            else:
                logger.warning(f"Tavily API failed: {resp.status_code}")
        except Exception as e:
            logger.warning(f"Tavily API exception: {str(e)}")
        return None

    async def _try_custom():
        try:
            from custom_tools.web_search_tool import search_web
            custom_data = await search_web(query, max_results=5)
            if custom_data and custom_data.get("results"):
                res_obj = {"source": "Custom Scraper", "quality_flag": "high", "search_results": []}
                for res in custom_data["results"]:
                    res_obj["search_results"].append({
                        "title": res.get("title", ""),
                        "snippet": res.get("truncated_content", ""),
                        "url": res.get("url", "")
                    })
                return json.dumps(res_obj)
        except Exception as e:
            logger.error(f"Custom search failed: {e}")
        return None

    # Execute based on preference with fallback
    if provider == "custom":
        res_str = await _try_custom()
        if res_str: return res_str
        result["error"] = "Custom search provider failed. (Strict failure mode, no fallback)"
        return json.dumps(result)
    elif provider == "tavily":
        res_str = await _try_tavily()
        if res_str: return res_str
        logger.warning("Tavily failed, falling back to Exa.")
        res_str = await _try_exa()
        if res_str: return res_str
    else:
        res_str = await _try_exa()
        if res_str: return res_str
        logger.warning("Exa failed, falling back to Tavily.")
        res_str = await _try_tavily()
        if res_str: return res_str

    result["error"] = "No fallback API keys available or all providers failed (Tavily/Exa)."
    return json.dumps(result)

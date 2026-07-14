"""
Mock external data providers for the Vendor Due Diligence prototype.
These simulate API calls to databases (OpenSanctions, corporate registries)
as well as generalized web search engines.

It includes dynamic logic to return "clean" data for standard vendors
and "toxic" data to trigger Supervisor anomalies for vendors with 
"risk" or "bad" in their name.
"""

import asyncio
import json

def _is_high_risk(name: str | list[str]) -> bool:
    """Helper to determine if we should mock a malicious payload."""
    if isinstance(name, list):
        text = " ".join(name).lower()
    else:
        text = str(name).lower()
    return "risk" in text or "bad" in text

import hashlib
async def perform_web_search(query: str) -> str:
    """Simulates querying a web search API (e.g., Google Custom Search/Serper)."""
    await asyncio.sleep(0.6)
    query_lower = query.lower()
    
    results = []
    
    # Deterministic supply chain generator based on query
    if "supply chain" in query_lower or "resilience" in query_lower or "supplier" in query_lower:
        h = int(hashlib.md5(query.encode()).hexdigest(), 16)
        s1 = f"Supplier {(h % 900) + 100} LLC"
        s2 = f"Global {(h % 90) + 10} Corp"
        s3 = f"Manufacturing Partner {(h % 9) + 1} Ltd"
        results.append({
            "title": "Supply Chain Disclosure and Logistics",
            "snippet": f"Audit reveals the primary direct suppliers are {s1}, {s2}, and {s3}."
        })

    if _is_high_risk(query):
        if "esg" in query_lower or "greenwashing" in query_lower or "social" in query_lower:
            results.append({"title": "Lawsuit over environmental damage", "snippet": "The company faces massive fines for illegal dumping and forced labor controversies."})
        elif "operations" in query_lower or "profile" in query_lower or "business model" in query_lower:
            results.append({"title": "Investigation into shell company", "snippet": "Authorities suspect the business is a front for unregulated crypto mining."})
        elif "supply chain" in query_lower or "resilience" in query_lower:
            results.append({"title": "Supply chain crisis", "snippet": "Critical dependency on sanctioned manufacturers revealed in recent audit."})
        elif "media" in query_lower or "news" in query_lower or "scandal" in query_lower:
            results.append({"title": "Executives indicted", "snippet": "Top executives arrested in wire fraud scheme."})
        elif "license" in query_lower or "certification" in query_lower:
            results.append({"title": "Trading License Revoked", "snippet": "Financial authority revokes license after widespread regulatory failures."})
        elif "finance" in query_lower or "debt" in query_lower:
            results.append({"title": "Hidden debts uncovered", "snippet": "Whistleblower reveals massive undisclosed liabilities to offshore entities."})
        else:
            results.append({"title": "High Risk Vendor warning", "snippet": "Multiple watchdogs have flagged this entity for unusual activities."})
    else:
        if "esg" in query_lower or "sustainability" in query_lower:
            results.append({"title": "Annual Sustainability Report", "snippet": "Company achieves carbon neutral status for 2023."})
        elif "operations" in query_lower or "profile" in query_lower:
            results.append({"title": "Leading B2B SaaS Provider", "snippet": "Company expands operations in software development sector."})
        elif not ("supply chain" in query_lower or "resilience" in query_lower or "supplier" in query_lower):
            results.append({"title": "Company news", "snippet": "Standard operations continuing steadily without disruptions."})
            
    return json.dumps({"search_results": results})

async def fetch_corporate_registry(company_name: str, country: str | None) -> str:
    await asyncio.sleep(0.5) # Simulate API latency
    
    data = {
        "status": "Active",
        "incorporation_date": "2015-04-12",
        "shareholders": ["John Doe", "Jane Smith"]
    }
    
    if _is_high_risk(company_name):
        data["shareholders"].append("Global Shell Holdings LLC")
        data["notes"] = "Recent transfer of 45% ownership to undisclosed offshore entity."
        
    return json.dumps(data)

async def verify_kyb_records(company_name: str, reg_id: str | None) -> str:
    await asyncio.sleep(0.5)
    
    data = {
        "legal_status": "Good Standing",
        "entity_type": "Limited Liability Company"
    }
    
    if _is_high_risk(company_name):
        data["legal_status"] = "Suspended - Failure to File Tax Returns"
        data["warnings"] = ["Registered address belongs to a known mail-forwarding service."]
        
    return json.dumps(data)

async def screen_sanctions(entities: list[str]) -> str:
    await asyncio.sleep(0.8)
    
    data = {"hits": []}
    
    if _is_high_risk(entities):
        # Trigger an OFAC hit for one of the entities
        data["hits"].append({
            "entity_name": "Global Shell Holdings LLC",
            "list": "OFAC SDN",
            "match_score": 0.98,
            "reason": "Associated with sanctioned proliferation network."
        })
        
    return json.dumps(data)

async def verify_licenses(company_name: str, country: str | None) -> str:
    await asyncio.sleep(0.5)
    
    data = {
        "iso_27001": "Valid until 2026",
        "trading_license": "Active"
    }
    
    if _is_high_risk(company_name):
        data["trading_license"] = "REVOKED - Pending investigation by local financial authority."
        
    return json.dumps(data)

async def fetch_financials(company_name: str, registration_id: str | None) -> str:
    await asyncio.sleep(0.6)
    
    data = {
        "revenue_yoy": "+12%",
        "debt_to_equity": 0.8,
        "cash_reserves": "$12M"
    }
    
    if _is_high_risk(company_name):
        data["debt_to_equity"] = 4.5
        data["undisclosed_liabilities"] = "$50M owed to Global Shell Holdings LLC"
        
    return json.dumps(data)

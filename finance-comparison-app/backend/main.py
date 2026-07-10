import asyncio
import os
import sys
import re
import urllib.parse
from pathlib import Path

# Add the root VDD Prototype directory to sys.path so we can import custom_tools
root_dir = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(root_dir))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
from dotenv import load_dotenv

from custom_tools.yfinance_tool import get_financial_statement

# Load environment variables
load_dotenv(root_dir / ".env")

app = FastAPI(title="Finance Comparison API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/compare_financials")
async def compare_financials(company_name: str):
    response_data = {
        "company_name": company_name,
        "yfinance": {"status": "pending", "data": None, "error": None},
        "fmp": {"status": "pending", "data": None, "error": None}
    }

    ticker = None

    # Fetch yfinance
    try:
        clean_name = re.sub(r'(?i)\b(inc|llc|corp|corporation|ltd|limited|plc|nv|n\.v\.|holdings?|group|ag|sa|ab|spa)(?:\b|\.|$)', '', company_name)
        clean_name = re.sub(r'[,\.\s]+', ' ', clean_name).strip()
        search_query = clean_name if clean_name else company_name
        search_query = urllib.parse.quote(search_query)

        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={search_query}"
        from curl_cffi import requests as cffi_requests
        resp = await asyncio.to_thread(
            cffi_requests.get,
            url,
            impersonate="chrome",
            timeout=10
        )
        search_data = resp.json() if resp.status_code == 200 else None
        
        if search_data and search_data.get("quotes"):
            ticker = search_data["quotes"][0].get("symbol")
            
        if ticker:
            income_statement = await asyncio.to_thread(get_financial_statement, ticker, "income")
            if "data_records" in income_statement:
                response_data["yfinance"]["status"] = "success"
                response_data["yfinance"]["data"] = income_statement["data_records"]
            else:
                response_data["yfinance"]["status"] = "error"
                response_data["yfinance"]["error"] = income_statement.get("error", "Unknown error")
        else:
            response_data["yfinance"]["status"] = "error"
            response_data["yfinance"]["error"] = f"Could not resolve ticker for {company_name}"
    except Exception as e:
        response_data["yfinance"]["status"] = "error"
        response_data["yfinance"]["error"] = str(e)

    # Fetch Alpha Vantage
    try:
        av_key = os.getenv("ALPHAVANTAGE_API_KEY", "demo")
        if ticker:
            av_url = f"https://www.alphavantage.co/query?function=INCOME_STATEMENT&symbol={ticker}&apikey={av_key}"
            async with httpx.AsyncClient() as client:
                av_resp = await client.get(av_url)
                if av_resp.status_code == 200:
                    data = av_resp.json()
                    if "annualReports" in data:
                        # Map Alpha Vantage fields to the table
                        mapped_data = [
                            {
                                "date": report.get("fiscalDateEnding"),
                                "revenue": report.get("totalRevenue"),
                                "grossProfit": report.get("grossProfit"),
                                "operatingIncome": report.get("operatingIncome"),
                                "netIncome": report.get("netIncomeFromContinuingOperations")
                            }
                            for report in data["annualReports"][:5]
                        ]
                        response_data["fmp"]["status"] = "success"
                        response_data["fmp"]["data"] = mapped_data
                    else:
                        response_data["fmp"]["status"] = "error"
                        response_data["fmp"]["error"] = data.get("Information", data.get("Note", "No annual reports returned from Alpha Vantage."))
                else:
                    response_data["fmp"]["status"] = "error"
                    response_data["fmp"]["error"] = f"Alpha Vantage API returned status {av_resp.status_code}"
        else:
            response_data["fmp"]["status"] = "error"
            response_data["fmp"]["error"] = f"Could not resolve ticker for {company_name}"
    except Exception as e:
        response_data["fmp"]["status"] = "error"
        response_data["fmp"]["error"] = str(e)

    return response_data

if __name__ == "__main__":
    import uvicorn
    # Make sure this runs on 8003 as requested
    uvicorn.run(app, host="0.0.0.0", port=8003)

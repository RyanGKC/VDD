import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from main import run_dd_with_ctx
from core.models import DDReport, DDContext, CompanyDetails

app = FastAPI(title="VDD Prototype API")

# Setup CORS to allow frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to the frontend origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

active_jobs = {}

class DDRequest(BaseModel):
    company_name: str
    registration_number: Optional[str] = None
    country: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    tax_id: Optional[str] = None
    use_mock: bool = False
    tiers_to_search: int = 1
    max_suppliers_per_node: int = 3
    job_id: Optional[str] = None

@app.post("/api/dd_report", response_model=DDReport)
async def generate_dd_report(request: DDRequest):
    ctx = DDContext(
        company_details=CompanyDetails(
            company_name=request.company_name,
            country=request.country,
            registration_number=request.registration_number,
        ),
        use_mock=request.use_mock,
        tiers_to_search=request.tiers_to_search,
        max_suppliers_per_node=request.max_suppliers_per_node
    )
    if request.job_id:
        active_jobs[request.job_id] = ctx
        
    try:
        report = await run_dd_with_ctx(ctx)
        return report
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if request.job_id:
            active_jobs.pop(request.job_id, None)

@app.get("/api/dd_status/{job_id}")
async def get_dd_status(job_id: str):
    ctx = active_jobs.get(job_id)
    if not ctx:
        return {"logs": []}
        
    formatted_logs = []
    for log in ctx.execution_log:
        try:
            ts, msg = log.split(" | ", 1)
            time_str = ts.split("T")[1].split(".")[0]
            formatted_logs.append({"text": msg, "time": time_str})
        except:
            formatted_logs.append({"text": log, "time": ""})
            
    return {"logs": formatted_logs}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

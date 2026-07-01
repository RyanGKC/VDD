import asyncio
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from main import run_dd_with_ctx
from core.models import DDReport, DDContext, CompanyDetails
from core.history_db import HistoryDB
from datetime import datetime, timezone
import json

app = FastAPI(title="VDD Prototype API")
history_db = HistoryDB()

# Setup CORS to allow frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to the frontend origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

active_jobs = {}
active_tasks = {}

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
    enable_parent_company: bool = False
    enable_parent_supply_chain: bool = False
    enable_rag: Optional[bool] = None

@app.post("/api/dd_report", response_model=DDReport)
async def generate_dd_report(request: DDRequest):
    import uuid
    from core.dependencies import (
        retrieval_engine, ingestion_pipeline,
        cache_gate, singleflight, background_tasks, vs
    )

    run_id = request.job_id if request.job_id else str(uuid.uuid4())

    ctx = DDContext(
        company_details=CompanyDetails(
            company_name=request.company_name,
            country=request.country,
            registration_number=request.registration_number,
        ),
        use_mock=request.use_mock,
        tiers_to_search=request.tiers_to_search,
        max_suppliers_per_node=request.max_suppliers_per_node,
        enable_parent_company=request.enable_parent_company,
        enable_parent_supply_chain=request.enable_parent_supply_chain,
        run_id=run_id,
        retrieval_engine=retrieval_engine,
        ingestion_pipeline=ingestion_pipeline,
        cache_gate=cache_gate,
        singleflight=singleflight,
        background_tasks=background_tasks,
    )
    if request.enable_rag is not None:
        ctx.enable_rag = request.enable_rag
    if request.job_id:
        active_jobs[request.job_id] = ctx
        
    try:
        # Wrap in a dedicated asyncio Task so we can safely cancel it externally
        task = asyncio.create_task(run_dd_with_ctx(ctx))
        if request.job_id:
            active_tasks[request.job_id] = task
            
        report = await task
        
        # Save to history database
        if request.job_id:
            history_db.save_report(
                job_id=request.job_id,
                company_name=request.company_name,
                overall_risk=report.overall_risk.value,
                report_json=report.model_dump_json()
            )
            
            # Embed into historical_reports for cross-run RAG comparison
            import uuid
            hist_id = str(uuid.uuid4())
            metadata = {
                "primary_entity_id": request.company_name,
                "report_id": request.job_id,
                "risk_rating": report.overall_risk.value,
                "date_generated": datetime.now(timezone.utc).isoformat()
            }
            vs.get_collection("historical_reports").add(
                documents=[f"Summary: {report.executive_summary}\n\nStrengths: {report.strengths}\n\nRed Flags: {report.red_flags}"],
                metadatas=[metadata],
                ids=[hist_id]
            )
            
        return report
    except asyncio.CancelledError:
        print(f"Job {request.job_id} was successfully cancelled.")
        raise HTTPException(status_code=499, detail="Client Closed Request")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if request.job_id:
            # Delay cleanup so the WebSocket has time to read final logs for extremely fast/cached runs
            async def delayed_cleanup():
                await asyncio.sleep(5)
                active_jobs.pop(request.job_id, None)
                active_tasks.pop(request.job_id, None)
                
                # Cleanup ephemeral vector store documents
                try:
                    from core.dependencies import vs
                    vs.get_collection("run_documents").delete(where={"run_id": run_id})
                    print(f"SYSTEM: Cleaned up run_documents for run_id={run_id}")
                except Exception as e:
                    print(f"SYSTEM: Failed to clean up run_documents: {e}")
                    
            asyncio.create_task(delayed_cleanup())

@app.websocket("/api/ws/dd_status/{job_id}")
async def ws_dd_status(websocket: WebSocket, job_id: str):
    await websocket.accept()
    print(f"[WS] Accepted connection for job {job_id}")
    
    # Wait briefly for job to register in active_jobs
    found = False
    for i in range(20):
        if job_id in active_jobs:
            found = True
            break
        await asyncio.sleep(0.1)
        
    print(f"[WS] Job {job_id} found in active_jobs: {found}")
    ctx = active_jobs.get(job_id)
    if not ctx:
        print(f"[WS] Closing connection because ctx is None for job {job_id}")
        await websocket.close(code=1000)
        return
        
    last_log_index = 0
    try:
        while True:
            current_len = len(ctx.execution_log)
            if current_len > last_log_index:
                new_logs = []
                for log in ctx.execution_log[last_log_index:current_len]:
                    try:
                        ts, msg = log.split(" | ", 1)
                        time_str = ts.split("T")[1].split(".")[0]
                        new_logs.append({"text": msg, "time": time_str})
                    except:
                        new_logs.append({"text": log, "time": ""})
                
                print(f"[WS] Sending {len(new_logs)} new logs to client")
                await websocket.send_json({"logs": new_logs})
                last_log_index = current_len
                
            # Exit loop if job finished or was removed
            if job_id not in active_jobs and last_log_index >= len(ctx.execution_log):
                print(f"[WS] Job {job_id} no longer in active_jobs and logs consumed. Closing.")
                await websocket.close(code=1000)
                break
                
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        print(f"WebSocket disconnected for job {job_id}")
    except Exception as e:
        print(f"WebSocket error for job {job_id}: {e}")

@app.post("/api/dd_cancel/{job_id}")
async def cancel_dd_job(job_id: str):
    task = active_tasks.get(job_id)
    if task and not task.done():
        task.cancel()
        return {"status": "cancelled", "job_id": job_id}
    return {"status": "not_found_or_finished", "job_id": job_id}

@app.get("/api/history")
async def get_history():
    return history_db.get_all_reports_metadata()

@app.get("/api/history/{job_id}")
async def get_history_report(job_id: str):
    report_json = history_db.get_report_by_job_id(job_id)
    if not report_json:
        raise HTTPException(status_code=404, detail="Report not found")
    # Return as JSON response to avoid double serialization since it's already a JSON string
    from fastapi.responses import JSONResponse
    return JSONResponse(content=json.loads(report_json))

class DeleteHistoryRequest(BaseModel):
    job_ids: list[str]

@app.delete("/api/history")
async def delete_history(request: DeleteHistoryRequest):
    try:
        history_db.delete_reports(request.job_ids)
        return {"status": "success", "deleted": len(request.job_ids)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)

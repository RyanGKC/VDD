import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from main import run_dd_with_ctx
from core.models import DDReport, DDContext, CompanyDetails
from core.history_db import HistoryDB
from datetime import datetime, timezone
import json
from fastapi.responses import Response
from jinja2 import Environment, FileSystemLoader
import os

# Ensure WeasyPrint can find Homebrew libraries on macOS Apple Silicon
if "DYLD_FALLBACK_LIBRARY_PATH" not in os.environ:
    os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = "/opt/homebrew/lib"
    
try:
    from weasyprint import HTML
except ImportError:
    HTML = None

# Hide neo4j notifications unless they are warnings or higher
logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)

@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.dependencies import neo4j
    await neo4j.setup_constraints()
    yield
    from core.dependencies import neo4j, http_client
    from custom_tools.web_search_tool import shutdown_browser
    await shutdown_browser()
    await neo4j.close()
    await http_client.aclose()

app = FastAPI(title="VDD Prototype API", lifespan=lifespan)
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
_cleanup_tasks = set()

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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks

@app.post("/api/dd_report", response_model=DDReport)
async def generate_dd_report(request: DDRequest, bg_tasks: BackgroundTasks):
    import uuid
    from core.dependencies import (
        retrieval_engine, ingestion_pipeline,
        cache_gate, singleflight, background_tasks, vs, checkpoint_db
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
    if checkpoint_db:
        ctx.checkpoint_db = checkpoint_db
        run_config = {
            "use_mock": request.use_mock,
            "tiers_to_search": request.tiers_to_search,
            "max_suppliers_per_node": request.max_suppliers_per_node,
            "enable_parent_company": request.enable_parent_company,
            "enable_parent_supply_chain": request.enable_parent_supply_chain,
            "enable_rag": request.enable_rag if request.enable_rag is not None else True
        }
        await checkpoint_db.start_run(
            run_id=run_id,
            vendor_name=request.company_name,
            company_details_json=ctx.company_details.model_dump_json(),
            run_config_json=json.dumps(run_config)
        )
        await checkpoint_db.enqueue_entity(
            run_id=run_id,
            entity_name=request.company_name,
            depth=request.tiers_to_search,
            parent=None,
            role='target'
        )

    if request.enable_rag is not None:
        ctx.enable_rag = request.enable_rag
    if request.job_id:
        # If the same job_id is re-submitted (React Strict Mode double-fire), cancel
        # the prior task for this id before starting a fresh one.
        if request.job_id in active_tasks:
            prior_task = active_tasks.pop(request.job_id)
            if not prior_task.done():
                prior_task.cancel()
        active_jobs[request.job_id] = ctx
        
    try:
        # Prevent concurrent duplicate requests from the frontend for the same company.
        # This guards against genuinely different job_ids for the same company name.
        for existing_job_id, existing_ctx in active_jobs.items():
            if existing_job_id != request.job_id and existing_ctx.company_details.company_name.lower() == request.company_name.lower():
                raise HTTPException(
                    status_code=409,
                    detail=f"A research job for '{request.company_name}' is already in progress (job_id: {existing_job_id})"
                )

        # Wrap in a dedicated asyncio Task so we can safely cancel it externally
        task = asyncio.create_task(run_dd_with_ctx(ctx))
        if request.job_id:
            active_tasks[request.job_id] = task
            
        report = await task
        
        # Save to history database
        if request.job_id and not ctx.saved_to_history:
            ctx.saved_to_history = True
            history_db.save_report(
                job_id=request.job_id,
                company_name=request.company_name,
                overall_risk=report.overall_risk.value,
                report_json=report.model_dump_json()
            )
            
            # Embed into historical_reports for cross-run RAG comparison
            import hashlib
            hist_id = hashlib.sha256(f"{request.company_name}|{request.job_id}".encode()).hexdigest()
            metadata = {
                "primary_entity_id": request.company_name,
                "report_id": request.job_id,
                "risk_rating": report.overall_risk.value,
                "date_generated": datetime.now(timezone.utc).isoformat()
            }
            vs.get_collection("historical_reports").upsert(
                documents=[f"Summary: {report.executive_summary}\n\nStrengths: {report.strengths}\n\nRed Flags: {report.red_flags}"],
                metadatas=[metadata],
                ids=[hist_id]
            )
            
        if checkpoint_db:
            await checkpoint_db.complete_run(run_id)
            
        try:
            from core.dependencies import vs
            vs.get_collection("run_documents").delete(where={"run_id": run_id})
            print(f"SYSTEM: Cleaned up run_documents for run_id={run_id}")
        except Exception as e:
            print(f"SYSTEM: Failed to clean up run_documents: {e}")
            
        return report
    except asyncio.CancelledError:
        print(f"Job {request.job_id} was successfully cancelled.")
        if 'task' in locals() and not task.done():
            task.cancel()
        if request.job_id:
            # Only pop if we are still the active task for this job_id.
            # A new strict-mode mount may have already overwritten it.
            if request.job_id in active_tasks and active_tasks[request.job_id] == task:
                active_tasks.pop(request.job_id)
            if request.job_id in active_jobs and active_jobs[request.job_id] == ctx:
                active_jobs.pop(request.job_id)
        raise HTTPException(status_code=499, detail="Client Closed Request")
    except HTTPException:
        # Re-raise HTTP exceptions so they don't get wrapped in a 500
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if request.job_id:
            # Delay cleanup so the WebSocket has time to read final logs for extremely fast/cached runs
            async def delayed_cleanup():
                await asyncio.sleep(5)
                # Only pop if we are still the active task for this job_id
                if active_tasks.get(request.job_id) is task:
                    active_jobs.pop(request.job_id, None)
                    active_tasks.pop(request.job_id, None)
                
            t = asyncio.create_task(delayed_cleanup())
            _cleanup_tasks.add(t)
            t.add_done_callback(_cleanup_tasks.discard)

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
    idle_counter = 0
    try:
        while True:
            # Check if the ctx was replaced (e.g. by an idempotent Strict Mode re-submission)
            current_ctx = active_jobs.get(job_id)
            if current_ctx and current_ctx is not ctx:
                print(f"[WS] Detected new ctx object for job {job_id}, resetting log cursor")
                ctx = current_ctx
                last_log_index = 0
                
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
                idle_counter = 0
            else:
                idle_counter += 1
                if idle_counter >= 100:  # 10 seconds (100 * 0.1s)
                    try:
                        await websocket.send_json({"logs": []})  # Keep-alive ping
                    except Exception:
                        pass
                    idle_counter = 0
                
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
async def cancel_dd_job(job_id: str, discard: bool = False):
    task = active_tasks.get(job_id)
    if task and not task.done():
        task.cancel()
        
    if discard:
        from core.dependencies import checkpoint_db, vs
        if checkpoint_db:
            await checkpoint_db.delete_runs([job_id])
        if vs:
            try:
                vs.get_collection("run_documents").delete(where={"run_id": job_id})
            except Exception:
                pass
        return {"status": "cancelled_and_discarded", "job_id": job_id}

    if task:
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

@app.get("/api/history/{job_id}/pdf")
async def get_history_report_pdf(job_id: str):
    if HTML is None:
        raise HTTPException(status_code=500, detail="WeasyPrint is not installed or configured correctly.")
        
    report_json = history_db.get_report_by_job_id(job_id)
    if not report_json:
        raise HTTPException(status_code=404, detail="Report not found")
        
    report_dict = json.loads(report_json)
    
    # Convert string dates back to datetime objects for the template
    if "generated_at" in report_dict and isinstance(report_dict["generated_at"], str):
        try:
            report_dict["generated_at"] = datetime.fromisoformat(report_dict["generated_at"].replace("Z", "+00:00"))
        except:
            pass
            
    # Setup Jinja2 environment
    env = Environment(loader=FileSystemLoader("core/templates"))
    template = env.get_template("report.html")
    
    # Render HTML
    rendered_html = template.render(report=report_dict)
    
    # Convert to PDF
    pdf_bytes = HTML(string=rendered_html).write_pdf()
    
    # Return as a downloadable file
    vendor_name = report_dict.get("vendor_name", "Vendor").replace(" ", "_")
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{vendor_name}_DD_Report.pdf"'
        }
    )

class DeleteHistoryRequest(BaseModel):
    job_ids: list[str]

@app.delete("/api/history")
async def delete_history(request: DeleteHistoryRequest):
    try:
        history_db.delete_reports(request.job_ids)
        return {"status": "success", "deleted": len(request.job_ids)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/dd_report/interrupted")
async def delete_interrupted_runs(request: DeleteHistoryRequest):
    try:
        from core.dependencies import checkpoint_db, vs
        if checkpoint_db:
            await checkpoint_db.delete_runs(request.job_ids)
        if vs:
            try:
                vs.get_collection("run_documents").delete(where={"run_id": {"$in": request.job_ids}})
            except Exception:
                pass
        return {"status": "success", "deleted": len(request.job_ids)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/dd_report/interrupted")
async def get_interrupted_runs():
    from core.dependencies import checkpoint_db
    if not checkpoint_db:
        return []
    runs = await checkpoint_db.get_interrupted_runs()
    return [run for run in runs if run["run_id"] not in active_jobs]

@app.post("/api/dd_report/resume/{run_id}", response_model=DDReport)
async def resume_dd_report(run_id: str):
    from core.dependencies import checkpoint_db
    
    run = await checkpoint_db.get_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Run '{run_id}' not found in checkpoint store.")
    if run["status"] == "completed":
        raise HTTPException(409, detail=f"Run '{run_id}' already completed.")
    
    # --- Rebuild DDContext from checkpoint ---
    company_details = CompanyDetails.model_validate_json(run["company_details_json"])
    
    # Load configuration
    run_config = {}
    if run.get("run_config_json"):
        try:
            run_config = json.loads(run["run_config_json"])
        except Exception:
            pass
            
    # Load and apply context/enrichment updates chronologically from supervisor interventions
    enrichment = {}
    interventions = await checkpoint_db.get_interventions(run_id)
    for intervention in interventions:
        if intervention["context_updates_json"]:
            try:
                updates = json.loads(intervention["context_updates_json"])
                if updates.get("updated_country"):
                    company_details.country = updates["updated_country"]
                if updates.get("updated_registration_number"):
                    company_details.registration_number = updates["updated_registration_number"]
                if updates.get("updated_address"):
                    company_details.address = updates["updated_address"]
                if updates.get("updated_website"):
                    company_details.website = updates["updated_website"]
                if updates.get("updated_tax_id"):
                    company_details.tax_id = updates["updated_tax_id"]
                if updates.get("new_enrichment"):
                    enrichment.update(updates["new_enrichment"])
            except Exception:
                pass
                
    from core.dependencies import (
        retrieval_engine, ingestion_pipeline,
        cache_gate, singleflight, background_tasks,
        vs, history_db
    )
    ctx = DDContext(
        company_details=company_details, 
        run_id=run_id,
        retrieval_engine=retrieval_engine,
        ingestion_pipeline=ingestion_pipeline,
        cache_gate=cache_gate,
        singleflight=singleflight,
        background_tasks=background_tasks,
        use_mock=run_config.get("use_mock", False),
        tiers_to_search=run_config.get("tiers_to_search", 1),
        max_suppliers_per_node=run_config.get("max_suppliers_per_node", 3),
        enable_parent_company=run_config.get("enable_parent_company", False),
        enable_parent_supply_chain=run_config.get("enable_parent_supply_chain", False),
        enable_rag=run_config.get("enable_rag", True),
        enrichment=enrichment
    )
    ctx.checkpoint_db = checkpoint_db
    
    # --- Reset any in-flight entities ---
    await checkpoint_db.reset_in_progress(run_id)
    
    # Hydration of completed steps happens automatically inside run_dd_with_ctx for both the target company and any child sub-pipelines
    if run_id in active_tasks:
        prior_task = active_tasks.pop(run_id)
        if not prior_task.done():
            prior_task.cancel()
    
    active_jobs[run_id] = ctx
    
    try:
        task = asyncio.create_task(run_dd_with_ctx(ctx))
        active_tasks[run_id] = task
        report = await task
        
        # Save to history database
        if not ctx.saved_to_history:
            ctx.saved_to_history = True
            history_db.save_report(
                job_id=run_id,
                company_name=run["vendor_name"],
                overall_risk=report.overall_risk.value,
                report_json=report.model_dump_json()
            )
            
            import hashlib
            hist_id = hashlib.sha256(f"{run['vendor_name']}|{run_id}".encode()).hexdigest()
            metadata = {
                "primary_entity_id": run["vendor_name"],
                "report_id": run_id,
                "risk_rating": report.overall_risk.value,
                "date_generated": datetime.now(timezone.utc).isoformat()
            }
            vs.get_collection("historical_reports").upsert(
                documents=[f"Summary: {report.executive_summary}\n\nStrengths: {report.strengths}\n\nRed Flags: {report.red_flags}"],
                metadatas=[metadata],
                ids=[hist_id]
            )
            
        await checkpoint_db.complete_run(run_id)
        
        try:
            vs.get_collection("run_documents").delete(where={"run_id": run_id})
            print(f"SYSTEM: Cleaned up run_documents for run_id={run_id}")
        except Exception as e:
            print(f"SYSTEM: Failed to clean up run_documents: {e}")
            
        return report
    except asyncio.CancelledError:
        print(f"Job {run_id} was successfully cancelled during resume.")
        if 'task' in locals() and not task.done():
            task.cancel()
        if run_id in active_tasks and active_tasks[run_id] == task:
            active_tasks.pop(run_id)
        if run_id in active_jobs and active_jobs[run_id] == ctx:
            active_jobs.pop(run_id)
        raise HTTPException(status_code=499, detail="Client Closed Request")
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        async def delayed_cleanup():
            await asyncio.sleep(5)
            if active_tasks.get(run_id) is task:
                active_jobs.pop(run_id, None)
                active_tasks.pop(run_id, None)
            
        t = asyncio.create_task(delayed_cleanup())
        _cleanup_tasks.add(t)
        t.add_done_callback(_cleanup_tasks.discard)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)

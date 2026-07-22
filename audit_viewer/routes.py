from fastapi import APIRouter, Query, HTTPException
from typing import List

from .models import AuditGraphResponse, RawChunksResponse
from .services import build_audit_graph, fetch_raw_chunks

router = APIRouter(prefix="/api/audit", tags=["audit"])

@router.get("/graph", response_model=AuditGraphResponse)
def get_audit_graph(
    run_id: str = Query(..., description="The ID of the pipeline run"),
    company_name: str = Query(..., description="The name of the company to scope the graph to")
):
    try:
        return build_audit_graph(run_id, company_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/chunks", response_model=RawChunksResponse)
def get_raw_chunks(
    chunk_ids: List[str] = Query(..., description="List of chunk IDs to retrieve")
):
    try:
        return fetch_raw_chunks(chunk_ids)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

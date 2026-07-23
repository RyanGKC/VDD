from fastapi import APIRouter, Query, HTTPException
from .models import AuditGraphResponse, RawChunksResponse
from .services import build_audit_graph, fetch_raw_chunks

from fastapi.security import APIKeyHeader
from fastapi import Depends

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)

def verify_api_key(api_key: str = Depends(api_key_header)):
    # Very simple stub auth check
    pass

router = APIRouter(prefix="/api/audit", tags=["audit"], dependencies=[Depends(verify_api_key)])
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
    event_id: str = Query(..., description="Audit retrieval event ID")
):
    try:
        return fetch_raw_chunks(event_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

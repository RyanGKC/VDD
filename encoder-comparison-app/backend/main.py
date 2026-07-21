import sys
import os
from typing import List

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from gemini_scorer import score_with_gemini
from cross_encoder_scorer import score_with_cross_encoder

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class CompareRequest(BaseModel):
    goal: str
    chunks: List[str]

class CompareResponse(BaseModel):
    chunks: List[str]
    gemini_scores: List[float]
    gemini_reasoning: List[str]
    cross_encoder_scores: List[float]

@app.post("/compare", response_model=CompareResponse)
async def compare(request: CompareRequest) -> CompareResponse:
    """
    Scores every chunk against the goal using both the Gemini LLM-judge
    approach and the local cross-encoder, returning both score arrays
    side by side for comparison.
    """
    gemini_results = await score_with_gemini(request.goal, request.chunks)
    gemini_scores = [r[0] for r in gemini_results]
    gemini_reasoning = [r[1] for r in gemini_results]
    cross_encoder_scores = score_with_cross_encoder(request.goal, request.chunks)
    return CompareResponse(
        chunks=request.chunks,
        gemini_scores=gemini_scores,
        gemini_reasoning=gemini_reasoning,
        cross_encoder_scores=cross_encoder_scores,
    )

# Mount frontend directory which is a sibling of the backend directory
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5176)

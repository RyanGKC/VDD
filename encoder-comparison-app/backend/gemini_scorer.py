import sys
import os
import logging
from typing import List

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from pydantic import BaseModel, Field

from core.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

_gemini_client = GeminiClient()


class ChunkScore(BaseModel):
    index: int = Field(..., description="The index of the passage being evaluated.")
    score: float = Field(..., description="Relevance score from 0.0 to 10.0.")
    reasoning: str = Field(..., description="Brief reasoning for the assigned score.")


class BatchedScoreResult(BaseModel):
    scores: List[ChunkScore]


async def score_with_gemini(goal_str: str, chunks: List[str]) -> List[tuple[float, str]]:
    """
    Uses Gemini as an LLM-judge to assign a relevance score (0.0-10.0)
    to each chunk against the given goal, in a single batched call so
    all chunks are scored with shared context and are comparable to
    each other within this run. Returns a list of (score, reasoning) tuples.
    """
    if not chunks:
        return []

    system_instruction = (
        "You are a relevance scoring engine. Your task is to evaluate how relevant "
        "each provided text passage is to the user's specific goal. Assign a score "
        "from 0.0 to 10.0, where 10.0 means the passage perfectly and directly addresses "
        "the goal, and 0.0 means it is completely irrelevant. Evaluate each passage independently, "
        "but keep your scores consistent and comparable across all passages in this batch."
    )

    prompt_parts = [f"Goal: {goal_str}\n\nPassages:"]
    for i, chunk in enumerate(chunks):
        prompt_parts.append(f"--- Passage {i} ---\n{chunk}\n")
    prompt = "\n".join(prompt_parts)

    try:
        result = await _gemini_client.generate_structured(
            system_instruction=system_instruction,
            prompt=prompt,
            schema=BatchedScoreResult,
        )
        by_index = {s.index: s for s in result.scores}
        return [
            (by_index[i].score, by_index[i].reasoning) if i in by_index else (0.0, "")
            for i in range(len(chunks))
        ]
    except Exception as e:
        logger.error(f"Error in Gemini batched scoring: {e}")
        return [(0.0, "")] * len(chunks)

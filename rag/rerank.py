import logging
from typing import List
from pydantic import BaseModel
from core.gemini_client import GeminiClient

logger = logging.getLogger(__name__)


class ChunkAssessment(BaseModel):
    index: int
    score: float        # 1.0 – 10.0
    is_relevant: bool   # LLM decides directly
    reasoning: str


class BatchedAssessmentResult(BaseModel):
    assessments: List[ChunkAssessment]


class Reranker:
    def __init__(self, gemini: GeminiClient):
        self.gemini = gemini

    async def assess_chunks(self, chunks: List[str], query: str) -> List[ChunkAssessment]:
        """
        Single LLM call that returns both a relevance score (1–10) and a binary
        is_relevant verdict per chunk.

        Fails closed: any chunk the LLM omits, or any exception during the call,
        produces is_relevant=False / score=0.0. This ensures an LLM failure flows
        through to a CacheGate MISS rather than silently serving unverified content.
        """
        if not chunks:
            return []

        system_instruction = (
            "You are a relevance assessment engine. For each passage, produce:\n"
            "1. score: a float from 1.0 (completely irrelevant) to 10.0 "
            "(perfectly answers the query).\n"
            "2. is_relevant: true only if the passage meaningfully answers or "
            "directly supports the query; false otherwise.\n"
            "3. reasoning: one sentence explaining your verdict.\n"
            "Evaluate each passage independently."
        )

        prompt_parts = [f"Query: {query}\n\nPassages:"]
        for i, chunk in enumerate(chunks):
            prompt_parts.append(f"--- Passage {i} ---\n{chunk}\n")
        prompt = "\n".join(prompt_parts)

        try:
            from rag.rate_limiter import run_foreground_generation
            res = await run_foreground_generation(
                lambda: self.gemini.generate_structured(
                    system_instruction=system_instruction,
                    prompt=prompt,
                    schema=BatchedAssessmentResult,
                )
            )
            by_index = {a.index: a for a in res.assessments}
            return [
                by_index.get(
                    i,
                    ChunkAssessment(
                        index=i, score=0.0, is_relevant=False,
                        reasoning="No verdict returned — failing closed"
                    ),
                )
                for i in range(len(chunks))
            ]
        except Exception as e:
            logger.error(f"Error in assess_chunks: {e}")
            return [
                ChunkAssessment(
                    index=i, score=0.0, is_relevant=False,
                    reasoning="Exception — failing closed"
                )
                for i in range(len(chunks))
            ]

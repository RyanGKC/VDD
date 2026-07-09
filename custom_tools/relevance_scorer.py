import logging
from pydantic import BaseModel
from core.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

class RelevanceScore(BaseModel):
    score: int   # 0-100
    reason: str  # brief, for logging/debugging

RELEVANCE_SYSTEM_INSTRUCTION = (
    "Score how directly this search result answers the specific question asked, "
    "not just whether it's topically related. A generic company profile, stock "
    "quote page, or tearsheet that merely mentions the topic should score lower "
    "than a page specifically analyzing or reporting on the question asked. "
    "Score 0-100."
)

import math
import asyncio

def _cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm_a = math.sqrt(sum(a * a for a in vec1))
    norm_b = math.sqrt(sum(b * b for b in vec2))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)

async def score_relevance(query: str, title: str, snippet: str, query_embedding: list[float] | None = None, snippet_embedding: list[float] | None = None) -> RelevanceScore:
    prompt = f"Query: {query}\nTitle: {title}\nSnippet: {snippet}"
    gemini = GeminiClient(model="gemini-2.5-flash-lite")

    async def get_llm_score():
        try:
            return await gemini.generate_structured(
                system_instruction=RELEVANCE_SYSTEM_INSTRUCTION,
                prompt=prompt, schema=RelevanceScore
            )
        except Exception as e:
            logger.warning(f"LLM relevance scoring failed: {e}")
            return RelevanceScore(score=50, reason=f"LLM error: {e}")

    async def get_semantic_score():
        try:
            q_emb = query_embedding
            text_emb = snippet_embedding

            # Only call embed API for embeddings not already provided
            if q_emb is None or text_emb is None:
                embeddings_needed = []
                if q_emb is None:
                    embeddings_needed.append(query)
                if text_emb is None:
                    embeddings_needed.append(f"{title} {snippet}")

                embeddings = await gemini.embed_content(embeddings_needed)

                idx = 0
                if q_emb is None:
                    q_emb = embeddings[idx]
                    idx += 1
                if text_emb is None:
                    text_emb = embeddings[idx]

            sim = _cosine_similarity(q_emb, text_emb)

            # Text-embedding-004 tends to cluster similarities between 0.4 and 0.9.
            # Stretch [0.5, 0.95] to [0, 100] to give the score dynamic range.
            normalized_sim = (sim - 0.5) / (0.95 - 0.5)
            return max(0, min(100, int(normalized_sim * 100)))
        except Exception as e:
            logger.warning(f"Semantic scoring failed: {e}")
        return 50

    llm_result, semantic_score = await asyncio.gather(get_llm_score(), get_semantic_score(), return_exceptions=True)
    
    # Handle the case where the gather returns an Exception instead of the return value
    # although get_llm_score and get_semantic_score already catch exceptions internally,
    # the return_exceptions=True acts as an extra guard.
    if isinstance(llm_result, Exception):
        llm_result = RelevanceScore(score=50, reason=f"Gather LLM error: {llm_result}")
    if isinstance(semantic_score, Exception):
        semantic_score = 50

    blended = int((llm_result.score * 0.6) + (semantic_score * 0.4))
    return RelevanceScore(score=blended, reason=f"LLM: {llm_result.score} | Semantic: {semantic_score}")

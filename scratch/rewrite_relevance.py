import re

with open("custom_tools/relevance_scorer.py", "r") as f:
    content = f.read()

new_content = """import logging
from pydantic import BaseModel
from core.gemini_client import GeminiClient
import math
import asyncio

logger = logging.getLogger(__name__)

class RelevanceScore(BaseModel):
    score: int   # 0-100
    reason: str  # brief, for logging/debugging

class ScoredSnippet(BaseModel):
    index: int
    score: int
    reason: str

class BatchRelevanceScore(BaseModel):
    scores: list[ScoredSnippet]

RELEVANCE_SYSTEM_INSTRUCTION = (
    "Score how directly this search result answers the specific question asked, "
    "not just whether it's topically related. A generic company profile, stock "
    "quote page, or tearsheet that merely mentions the topic should score lower "
    "than a page specifically analyzing or reporting on the question asked. "
    "Score 0-100."
)

def _cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm_a = math.sqrt(sum(a * a for a in vec1))
    norm_b = math.sqrt(sum(b * b for b in vec2))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)

def chunk_items(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]

def reconcile_relevance_batch(chunk: list[dict], scores: list[ScoredSnippet]) -> dict[int, ScoredSnippet]:
    by_index = {s.index: s for s in scores}
    expected_indices = {s["index"] for s in chunk}
    missing = expected_indices - set(by_index.keys())
    extra = set(by_index.keys()) - expected_indices
    
    if missing or extra:
        logger.warning(f"Batch stitching mismatch — missing: {missing}, unexpected: {extra}")
        # Discard extras, let missing fall through to fallback
        
    return by_index

async def score_relevance_batch(query: str, chunk: list[dict]) -> list[ScoredSnippet]:
    if not chunk:
        return []
        
    prompt = f"Query: {query}\n\nSnippets:\n\n"
    for s in chunk:
        prompt += f"--- Snippet {s['index']} ---\nTitle: {s['title']}\nSnippet: {s['snippet']}\n\n"
    
    gemini = GeminiClient(model="gemini-2.5-flash-lite")
    
    try:
        response = await gemini.generate_structured(
            system_instruction=RELEVANCE_SYSTEM_INSTRUCTION,
            prompt=prompt,
            schema=BatchRelevanceScore,
        )
        reconciled = reconcile_relevance_batch(chunk, response.scores)
    except Exception as e:
        logger.warning(f"Batch relevance scoring failed for chunk: {e}")
        reconciled = {}
        
    final_scores = []
    for s in chunk:
        if s["index"] in reconciled:
            final_scores.append(reconciled[s["index"]])
        else:
            final_scores.append(ScoredSnippet(index=s["index"], score=50, reason="fallback: batch call failed or dropped index"))
            
    return final_scores

async def get_semantic_score(query: str, title: str, snippet: str, query_embedding: list[float] | None = None, snippet_embedding: list[float] | None = None) -> float:
    try:
        q_emb = query_embedding
        text_emb = snippet_embedding
        if q_emb is None or text_emb is None:
            embeddings_needed = []
            if q_emb is None:
                embeddings_needed.append(query)
            if text_emb is None:
                embeddings_needed.append(f"{title} {snippet}")
            gemini = GeminiClient(model="gemini-2.5-flash-lite")
            embeddings = await gemini.embed_content(embeddings_needed)
            idx = 0
            if q_emb is None:
                q_emb = embeddings[idx]
                idx += 1
            if text_emb is None:
                text_emb = embeddings[idx]
        sim = _cosine_similarity(q_emb, text_emb)
        normalized_sim = (sim - 0.5) / (0.95 - 0.5)
        return max(0, min(100, int(normalized_sim * 100)))
    except Exception as e:
        logger.warning(f"Semantic scoring failed: {e}")
    return 50.0

async def batch_score_all_relevance(query: str, snippets: list[dict], query_embedding: list[float] | None = None, snippet_embeddings: dict[str, list[float]] | None = None) -> list[RelevanceScore]:
    # Ensure every snippet has an index
    for i, s in enumerate(snippets):
        s["index"] = i
        
    CHUNK_SIZE = 12
    chunks = chunk_items(snippets, CHUNK_SIZE)
    
    # Run LLM scoring batches
    llm_results_nested = await asyncio.gather(*[score_relevance_batch(query, c) for c in chunks])
    llm_results = [item for chunk_result in llm_results_nested for item in chunk_result]
    
    llm_by_index = {s.index: s for s in llm_results}
    
    # Run Semantic scoring
    snippet_embeddings_map = snippet_embeddings or {}
    
    async def compute_semantic(s):
        href = s.get("href", "")
        return await get_semantic_score(query, s.get("title", ""), s.get("body", ""), query_embedding, snippet_embeddings_map.get(href))
        
    semantic_scores = await asyncio.gather(*[compute_semantic(s) for s in snippets])
    
    final_relevance = []
    for idx, s in enumerate(snippets):
        llm_score = llm_by_index.get(s["index"], ScoredSnippet(index=s["index"], score=50, reason="fallback: missing index"))
        sem_score = semantic_scores[idx]
        blended = int((llm_score.score * 0.6) + (sem_score * 0.4))
        final_relevance.append(RelevanceScore(score=blended, reason=f"LLM: {llm_score.score} | Semantic: {sem_score}"))
        
    return final_relevance
"""

with open("custom_tools/relevance_scorer.py", "w") as f:
    f.write(new_content)

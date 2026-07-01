import logging
from typing import List, Dict
from pydantic import BaseModel
from core.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

class ChunkVerdict(BaseModel):
    index: int
    concerns_entity: bool
    reasoning: str

class BatchedRerankResult(BaseModel):
    verdicts: List[ChunkVerdict]

class Reranker:
    def __init__(self, gemini: GeminiClient):
        self.gemini = gemini

    async def rerank_chunks(self, chunks: List[str], entity_name: str) -> List[str]:
        """
        Filters out chunks that do not substantively report data about the target entity.
        Uses batched logic to reduce LLM API calls.
        """
        if not chunks:
            return []
            
        system_instruction = (
            "You are a verification engine. You must decide whether each given passage "
            "substantively reports data about the specified entity, or if it primarily "
            "concerns a different entity. Return true if it concerns the target entity. "
            "Evaluate each passage independently."
        )
        
        prompt_parts = [f"Target Entity: {entity_name}\n\nPassages:"]
        for i, chunk in enumerate(chunks):
            prompt_parts.append(f"--- Passage {i} ---\n{chunk}\n")
            
        prompt = "\n".join(prompt_parts)
        
        try:
            res = await self.gemini.generate_structured(
                system_instruction=system_instruction,
                prompt=prompt,
                schema=BatchedRerankResult,
            )
            
            valid_chunks = []
            verdicts_by_index = {v.index: v for v in res.verdicts}
            
            for i, chunk in enumerate(chunks):
                verdict = verdicts_by_index.get(i)
                if verdict and verdict.concerns_entity:
                    valid_chunks.append(chunk)
                elif verdict:
                    logger.debug(f"Reranker dropped chunk {i} for {entity_name}. Reason: {verdict.reasoning}")
                else:
                    # Missing verdict, default to keeping
                    valid_chunks.append(chunk)
                    
            return valid_chunks
        except Exception as e:
            logger.error(f"Error in batched reranking: {e}")
            # Default to keeping all if the API call fails
            return chunks

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

async def score_relevance(query: str, title: str, snippet: str) -> RelevanceScore:
    try:
        gemini = GeminiClient(model="gemini-2.5-flash-lite")
        prompt = f"Query: {query}\nTitle: {title}\nSnippet: {snippet}"
        return await gemini.generate_structured(
            system_instruction=RELEVANCE_SYSTEM_INSTRUCTION,
            prompt=prompt,
            schema=RelevanceScore
        )
    except Exception as e:
        logger.warning(f"Relevance scoring failed: {e}")
        # Fail neutral — don't let a scoring error silently deprioritize a result to zero
        return RelevanceScore(score=50, reason=f"Scoring error: {e}")

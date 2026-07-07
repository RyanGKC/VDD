import logging
from pydantic import BaseModel
from core.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

class QueryVariants(BaseModel):
    queries: list[str]

EXPANSION_SYSTEM_INSTRUCTION = (
    "Generate 3 alternative search queries that would surface specific, detailed "
    "content answering the user's underlying question — not just generic company "
    "profile pages, stock quote pages, or news aggregator listings. Favor phrasings "
    "that match how specialist analysis content (industry reports, competitor "
    "comparisons, market share breakdowns, sector analysis) would actually be "
    "titled or indexed."
)

async def expand_query(original_query: str) -> list[str]:
    try:
        gemini = GeminiClient(model="gemini-2.5-flash-lite")
        result = await gemini.generate_structured(
            system_instruction=EXPANSION_SYSTEM_INSTRUCTION,
            prompt=f"Original query: {original_query}",
            schema=QueryVariants
        )
        variants = [original_query] + result.queries
        logger.info(f"Expanded '{original_query}' into {len(variants)} query variants")
        return variants
    except Exception as e:
        logger.warning(f"Query expansion failed for '{original_query}': {e}")
        return [original_query]  # fail open — fall back to original query only

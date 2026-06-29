# Wrapper around Google's Gemini API (Redirected to OpenAI).

from __future__ import annotations

import logging
from core.openai_client import OpenAIClient

logger = logging.getLogger(__name__)


class GeminiClient(OpenAIClient):
    def __init__(self, model: str = "gpt-4o-mini") -> None:
        # Map Gemini models to OpenAI's gpt-4o-mini
        if "gemini" in model:
            logger.info("Mapping Gemini model '%s' to OpenAI 'gpt-4o-mini'", model)
            model = "gpt-4o-mini"
        super().__init__(model=model)

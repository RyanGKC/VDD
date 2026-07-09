# Native wrapper around Google's Gemini API via google-genai

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Type, TypeVar

from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential
import asyncio

_GEMINI_SEMAPHORE = None

def _get_semaphore():
    global _GEMINI_SEMAPHORE
    if _GEMINI_SEMAPHORE is None:
        _GEMINI_SEMAPHORE = asyncio.Semaphore(10)
    return _GEMINI_SEMAPHORE

from google import genai
from google.genai import types

from dotenv import load_dotenv
from core.cache import PersistentCache

logger = logging.getLogger(__name__)

# Load local environment variables from core/.env if available
env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

cache_db = PersistentCache()

T = TypeVar("T", bound=BaseModel)


class GeminiClient:
    def __init__(self, model: str | None = None, use_cache: bool = False) -> None:
        self._model = model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        self.use_cache = use_cache
        
        # Check if enterprise mode is enabled
        use_vertex = os.getenv("GOOGLE_GENAI_USE_ENTERPRISE", "false").lower() == "true"
        if use_vertex:
            project = os.getenv("GOOGLE_CLOUD_PROJECT")
            location = os.getenv("GOOGLE_CLOUD_LOCATION")
            self._client = genai.Client(vertexai=True, project=project, location=location)
        else:
            # Assumes GOOGLE_API_KEY is available in the environment
            self._client = genai.Client()
            
    async def close(self) -> None:
        pass

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        reraise=True,
    )
    async def generate_structured(
        self,
        *,
        system_instruction: str,
        prompt: str,
        schema: Type[T],
        enable_search: bool = False,
    ) -> T:
        cache_key = None
        if self.use_cache:
            cache_key = f"llm|{self._model}|{system_instruction}|{prompt}|{schema.__name__}|{enable_search}"
            cached_val = cache_db.get(cache_key, use_mock=True)
            if cached_val:
                import asyncio
                await asyncio.sleep(0.5) # Yield to event loop and simulate network delay
                return schema.model_validate_json(cached_val)
                
        config_kwargs = {
            "system_instruction": system_instruction,
            "response_mime_type": "application/json",
            "response_schema": schema,
            "temperature": 0.1,
        }
        
        if enable_search:
            config_kwargs["tools"] = [{"google_search": {}}]

        # Call Gemini asynchronously
        async with _get_semaphore():
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        
        if not response.text:
            finish_reason = getattr(response.candidates[0], 'finish_reason', 'UNKNOWN') if response.candidates else 'NO_CANDIDATES'
            logger.error(f"Gemini returned an empty response. Finish reason: {finish_reason}")
            raise ValueError(f"Gemini returned an empty response. Finish reason: {finish_reason}")
            
        try:
            # Parse JSON using pydantic
            obj = schema.model_validate_json(response.text)
            if self.use_cache and cache_key:
                cache_db.set(cache_key, obj.model_dump_json(), use_mock=True)
            return obj
        except Exception as exc:
            logger.error("Gemini returned unparseable output: %s\nText: %s", exc, response.text)
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        reraise=True,
    )
    async def embed_content(self, texts: list[str]) -> list[list[float]]:
        async with _get_semaphore():
            response = await self._client.aio.models.embed_content(
                model="text-embedding-004",
                contents=texts,
            )
        return [emb.values for emb in response.embeddings]

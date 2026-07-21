# Native wrapper around Google's Gemini API via google-genai

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Type, TypeVar
import threading
import asyncio

from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

_GENERATION_SEMAPHORE = None
_EMBEDDING_SEMAPHORE = None
_CLIENT = None
_CREDENTIALS = None
_TOKEN_LOCK = threading.Lock()

def _get_generation_semaphore():
    global _GENERATION_SEMAPHORE
    if _GENERATION_SEMAPHORE is None:
        _GENERATION_SEMAPHORE = asyncio.Semaphore(int(os.getenv("GEMINI_GENERATION_CONCURRENCY", "50")))
    return _GENERATION_SEMAPHORE

def _get_embedding_semaphore():
    global _EMBEDDING_SEMAPHORE
    if _EMBEDDING_SEMAPHORE is None:
        _EMBEDDING_SEMAPHORE = asyncio.Semaphore(int(os.getenv("GEMINI_EMBEDDING_CONCURRENCY", "100")))
    return _EMBEDDING_SEMAPHORE

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

def get_shared_client() -> genai.Client:
    global _CLIENT
    if _CLIENT is None:
        _init_shared_client()
    return _CLIENT

def get_shared_credentials():
    global _CREDENTIALS
    if _CREDENTIALS is None:
        _init_shared_client()
    return _CREDENTIALS

def _init_shared_client(force: bool = False) -> None:
    global _CREDENTIALS, _CLIENT
    if force:
        _CLIENT = None
        _CREDENTIALS = None
        
    use_vertex = os.getenv("GOOGLE_GENAI_USE_ENTERPRISE", "false").lower() == "true"
    if use_vertex:
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        location = os.getenv("GOOGLE_CLOUD_LOCATION")
        
        import google.auth
        _CREDENTIALS, default_project = google.auth.default()
        if not project:
            project = default_project
            
        _CLIENT = genai.Client(
            vertexai=True,
            project=project,
            location=location,
            credentials=_CREDENTIALS
        )
    else:
        _CLIENT = genai.Client()
        _CREDENTIALS = None

def ensure_valid_token_sync() -> None:
    credentials = get_shared_credentials()
    if credentials and not credentials.valid:
        with _TOKEN_LOCK:
            if not credentials.valid:
                from google.auth.transport.requests import Request
                
                @retry(
                    stop=stop_after_attempt(5),
                    wait=wait_exponential(multiplier=1, min=2, max=10),
                    reraise=True,
                )
                def _do_refresh():
                    credentials.refresh(Request())
                    
                try:
                    _do_refresh()
                    logger.info("Successfully refreshed Vertex AI OAuth token (sync)")
                except Exception as e:
                    logger.error(f"Failed to refresh token (sync): {e}")
                    raise

async def ensure_valid_token_async() -> None:
    credentials = get_shared_credentials()
    if credentials and not credentials.valid:
        # Run sync refresh in background thread to avoid blocking event loop
        await asyncio.to_thread(ensure_valid_token_sync)


class GeminiClient:
    def __init__(self, model: str | None = None, use_cache: bool = False) -> None:
        self._model = model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        self.use_cache = use_cache
        self._client = get_shared_client()
        self._credentials = get_shared_credentials()

    def _init_client(self) -> None:
        # Re-initialize shared client if needed
        _init_shared_client(force=True)
        self._client = get_shared_client()
        self._credentials = get_shared_credentials()
            
    async def close(self) -> None:
        pass

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=30),
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
                await asyncio.sleep(0.5)
                return schema.model_validate_json(cached_val)
                
        config_kwargs = {
            "system_instruction": system_instruction,
            "response_mime_type": "application/json",
            "response_schema": schema,
            "temperature": 0.1,
        }
        
        if enable_search:
            config_kwargs["tools"] = [{"google_search": {}}]

        await ensure_valid_token_async()
        try:
            async with _get_generation_semaphore():
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=types.GenerateContentConfig(**config_kwargs),
                )
        except Exception as e:
            logger.warning(f"Re-initializing Gemini client due to generation error: {e}")
            self._init_client()
            raise
        
        if not response.text:
            finish_reason = getattr(response.candidates[0], 'finish_reason', 'UNKNOWN') if response.candidates else 'NO_CANDIDATES'
            logger.error(f"Gemini returned an empty response. Finish reason: {finish_reason}")
            raise ValueError(f"Gemini returned an empty response. Finish reason: {finish_reason}")
            
        try:
            obj = schema.model_validate_json(response.text)
            if self.use_cache and cache_key:
                cache_db.set(cache_key, obj.model_dump_json(), use_mock=True)
            return obj
        except Exception as exc:
            logger.error("Gemini returned unparseable output: %s\nText: %s", exc, response.text)
            raise

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        reraise=True,
    )
    async def embed_content(self, texts: list[str]) -> list[list[float]]:
        await ensure_valid_token_async()
        try:
            async with _get_embedding_semaphore():
                response = await self._client.aio.models.embed_content(
                    model="text-embedding-004",
                    contents=texts,
                )
        except Exception as e:
            logger.warning(f"Re-initializing Gemini client due to embedding error: {e}")
            self._init_client()
            raise
        return [emb.values for emb in response.embeddings]

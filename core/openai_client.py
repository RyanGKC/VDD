# Wrapper around OpenAI's API.

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Type, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from dotenv import load_dotenv
from core.cache import PersistentCache

logger = logging.getLogger(__name__)

# Load local environment variables from core/.env if available
env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

cache_db = PersistentCache()

T = TypeVar("T", bound=BaseModel)


class OpenAIClient:
    def __init__(self, model: str = "gpt-4o-mini", use_cache: bool = False) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self.use_cache = use_cache

    async def close(self) -> None:
        await self._client.close()

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
    ) -> T:
        cache_key = None
        if self.use_cache:
            cache_key = f"llm|{self._model}|{system_instruction}|{prompt}|{schema.__name__}"
            cached_val = cache_db.get(cache_key, use_mock=True)
            if cached_val:
                return schema.model_validate_json(cached_val)

        # Call OpenAI asynchronously using structured outputs via beta.chat.completions.parse
        response = await self._client.beta.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            response_format=schema,
            temperature=0.1,
        )

        parsed_obj = response.choices[0].message.parsed
        if parsed_obj is not None:
            if self.use_cache and cache_key:
                cache_db.set(cache_key, parsed_obj.model_dump_json(), use_mock=True)
            return parsed_obj

        # Fallback manual validation if parsed is somehow None but content is present
        content = response.choices[0].message.content
        if content is not None:
            try:
                obj = schema.model_validate(json.loads(content))
                if self.use_cache and cache_key:
                    cache_db.set(cache_key, obj.model_dump_json(), use_mock=True)
                return obj
            except (json.JSONDecodeError, ValueError) as exc:
                logger.error("OpenAI returned unparseable output: %s", exc)
                raise

        raise ValueError("OpenAI returned an empty response with no choices or content.")

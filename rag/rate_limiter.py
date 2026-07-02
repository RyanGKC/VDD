import asyncio
import os
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")

FOREGROUND_GEN_LIMIT = int(os.getenv("RAG_FOREGROUND_GEN_LIMIT", "15"))
BACKGROUND_GEN_LIMIT = int(os.getenv("RAG_BACKGROUND_GEN_LIMIT", "4"))
BACKGROUND_EMBED_LIMIT = int(os.getenv("RAG_BACKGROUND_EMBED_LIMIT", "6"))

foreground_generation_sem = asyncio.Semaphore(FOREGROUND_GEN_LIMIT)
background_generation_sem = asyncio.Semaphore(BACKGROUND_GEN_LIMIT)
background_embedding_sem  = asyncio.Semaphore(BACKGROUND_EMBED_LIMIT)

async def run_foreground_generation(coro_factory: Callable[[], Awaitable[T]]) -> T:
    async with foreground_generation_sem:
        return await coro_factory()

async def run_background_generation(coro_factory: Callable[[], Awaitable[T]]) -> T:
    async with background_generation_sem:
        return await coro_factory()

async def run_background_embedding(coro_factory: Callable[[], Awaitable[T]]) -> T:
    async with background_embedding_sem:
        return await coro_factory()

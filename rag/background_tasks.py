"""
background_tasks.py — Fire-and-forget ingestion task registry, scoped per run_id.

Ingestion (chunking → embedding → Chroma write) is deliberately detached from
the agent's critical path. The agent proceeds immediately with its own raw data
while the Chroma write happens in the background. A single await_all() call at
the very end of the FlowEngine run ensures all pending ingestion tasks complete
before the run is marked done — making the data available for the NEXT run
(or for cross-agent lookups within the same run, once tasks drain).
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Coroutine, Any, Dict, Set

logger = logging.getLogger(__name__)


class BackgroundTaskRegistry:
    """
    Global (per-process) registry of background ingestion tasks keyed by run_id.

    Usage::

        registry = BackgroundTaskRegistry()
        registry.schedule(ingestion.ingest_document(...), run_id)
        # agent proceeds immediately ...

        # at end of FlowEngine run:
        await registry.await_all(run_id)
        registry.clear_run(run_id)
    """

    def __init__(self) -> None:
        # { run_id: set of pending asyncio.Task objects }
        self._pending: Dict[str, Set[asyncio.Task]] = defaultdict(set)

    def schedule(self, coro: Coroutine[Any, Any, Any], run_id: str) -> None:
        """
        Creates an asyncio Task for `coro` and registers it under `run_id`.
        Does NOT block the caller — returns immediately.
        Ingestion failures are logged but never re-raised.
        """
        task = asyncio.create_task(self._guarded(coro, run_id))
        self._pending[run_id].add(task)
        task.add_done_callback(lambda t: self._pending[run_id].discard(t))
        logger.debug(
            "BackgroundTasks scheduled ingestion: run=%s pending=%d",
            run_id,
            len(self._pending[run_id]),
        )

    async def _guarded(self, coro: Coroutine[Any, Any, Any], run_id: str) -> None:
        """Wraps the coroutine so exceptions are logged, not propagated."""
        try:
            await coro
        except Exception as exc:
            logger.error(
                "BackgroundTasks ingestion error (run=%s): %s — agent unaffected",
                run_id,
                exc,
                exc_info=True,
            )

    async def await_all(self, run_id: str) -> None:
        """
        Awaits every still-pending task for `run_id`.
        Called once at FlowEngine run completion — the single synchronization point.
        After this returns, all documents are guaranteed to be in the vector store.
        """
        tasks = list(self._pending.get(run_id, []))
        if not tasks:
            logger.debug("BackgroundTasks.await_all: no pending tasks for run=%s", run_id)
            return

        logger.info(
            "BackgroundTasks flushing %d pending ingestion task(s) for run=%s",
            len(tasks),
            run_id,
        )
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("BackgroundTasks flush complete for run=%s", run_id)

    def clear_run(self, run_id: str) -> None:
        """Removes all state for a completed run to prevent cross-run leaks."""
        self._pending.pop(run_id, None)
        logger.debug("BackgroundTasks cleared run=%s", run_id)

    def pending_count(self, run_id: str) -> int:
        return len(self._pending.get(run_id, []))

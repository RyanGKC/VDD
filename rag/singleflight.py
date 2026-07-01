"""
singleflight.py — Per-fingerprint locking to prevent duplicate concurrent fetches.

When multiple agents in the same run need the same external document, only one
makes the real network call. All other waiters receive the same result when
the leader's fetch resolves.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class FetchOutcome:
    role: str      # "leader" | "follower"
    data: Optional[str] = None   # raw fetched data (None for leader until complete)


class _InFlight:
    """Tracks a single in-flight fetch and lets followers await its result."""

    def __init__(self) -> None:
        self._future: asyncio.Future[Optional[str]] = asyncio.get_running_loop().create_future()

    def resolve(self, data: Optional[str]) -> None:
        if not self._future.done():
            self._future.set_result(data)

    def fail(self, exc: Exception) -> None:
        if not self._future.done():
            self._future.set_exception(exc)

    async def wait(self) -> Optional[str]:
        return await self._future


class SingleFlight:
    """
    In-memory, per-run deduplication of concurrent external fetches.

    Usage::

        sf = SingleFlight()
        outcome = await sf.acquire_or_wait(fingerprint_key, run_id)
        if outcome.role == "leader":
            raw = await do_actual_fetch()
            sf.resolve(fingerprint_key, run_id, raw)   # wake up all followers
        else:
            raw = outcome.data    # received from leader

    Thread/task safety: asyncio single-threaded event loop — no locks needed,
    but all mutations must happen within the same thread.
    """

    def __init__(self) -> None:
        # { run_id: { fingerprint_key: _InFlight } }
        self._registry: Dict[str, Dict[str, _InFlight]] = {}

    def _get_run(self, run_id: str) -> Dict[str, _InFlight]:
        if run_id not in self._registry:
            self._registry[run_id] = {}
        return self._registry[run_id]

    async def acquire_or_wait(self, fingerprint_key: str, run_id: str) -> FetchOutcome:
        """
        Returns immediately as LEADER if no fetch is in-flight for this key.
        Blocks until the leader resolves and returns as FOLLOWER with its data.
        """
        run = self._get_run(run_id)

        if fingerprint_key not in run:
            # This caller is the leader — register and proceed
            inflight = _InFlight()
            run[fingerprint_key] = inflight
            logger.debug("SingleFlight LEADER: key=%s run=%s", fingerprint_key[:12], run_id)
            return FetchOutcome(role="leader")

        # This caller is a follower — wait for the leader
        logger.debug(
            "SingleFlight FOLLOWER waiting: key=%s run=%s", fingerprint_key[:12], run_id
        )
        inflight = run[fingerprint_key]
        data = await inflight.wait()
        logger.debug("SingleFlight FOLLOWER received data: key=%s", fingerprint_key[:12])
        return FetchOutcome(role="follower", data=data)

    def resolve(self, fingerprint_key: str, run_id: str, data: Optional[str]) -> None:
        """Called by the leader after its fetch completes successfully."""
        run = self._get_run(run_id)
        inflight = run.get(fingerprint_key)
        if inflight:
            inflight.resolve(data)
            logger.debug("SingleFlight resolved: key=%s", fingerprint_key[:12])

    def fail(self, fingerprint_key: str, run_id: str, exc: Exception) -> None:
        """Called by the leader if its fetch raised an exception."""
        run = self._get_run(run_id)
        inflight = run.get(fingerprint_key)
        if inflight:
            inflight.fail(exc)
            logger.warning("SingleFlight failed: key=%s err=%s", fingerprint_key[:12], exc)

    def clear_run(self, run_id: str) -> None:
        """Remove all state for a completed run to prevent cross-run leaks."""
        self._registry.pop(run_id, None)
        logger.debug("SingleFlight cleared run=%s", run_id)

"""
cache_gate.py — Fast pre-fetch check: does a usable cached chunk set exist?

This is the entry point agents call BEFORE making any external API call.
A HIT means the data is already in Chroma, entity-scoped, and fresh — the
agent skips the external call entirely and uses the cached chunks directly.
A MISS means the agent should proceed with the real fetch (through singleflight).

Freshness windows per source type:
  - "web_search" / "news"     : 24 hours
  - "sec_filing" / "filing"   : 30 days
  - "sanctions" / "psc"       : 7 days
  - default                   : 24 hours
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from rag.entity_resolver import EntityResolver
from rag.vector_store import VectorStore
from rag.rerank import Reranker
from rag.cache_gate_rerank import rerank_and_group_documents

logger = logging.getLogger(__name__)

# Freshness windows by source_type (in hours)
_FRESHNESS_HOURS: dict[str, int] = {
    "web_search": 24,
    "news": 24,
    "sec_filing": 720,   # 30 days
    "filing": 720,
    "sanctions": 168,    # 7 days
    "psc": 168,
    "corporate_registry": 168,
    "kyb": 168,
    "financials": 720,
    "adverse_media": 24,
}
_DEFAULT_FRESHNESS_HOURS = 24


@dataclass
class CacheResult:
    status: str           # "HIT" | "MISS"
    chunks: Optional[List[str]] = None


class CacheGate:
    """
    Fast pre-fetch cache check, local only (no external network calls).

    Resolves the entity via EntityResolver, then queries Chroma for fresh,
    entity-scoped chunks matching the requested document kind.
    """

    def __init__(self, vector_store: VectorStore, entity_resolver: EntityResolver, reranker: Reranker) -> None:
        self.vs = vector_store
        self.resolver = entity_resolver
        self.reranker = reranker

    def _freshness_cutoff(self, document_kind: str) -> str:
        """Returns an ISO-format datetime string for the oldest acceptable chunk."""
        hours = _FRESHNESS_HOURS.get(document_kind, _DEFAULT_FRESHNESS_HOURS)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return cutoff.isoformat()

    async def check(
        self,
        entity_name: str,
        entity_type: str,
        document_kind: str,
        goal_str: str,
        run_id: Optional[str] = None,
    ) -> CacheResult:
        """
        Returns HIT (with chunks) if fresh, entity-correct cached data exists.
        Returns MISS otherwise. Always fast — no external calls.
        """
        try:
            # 1. Resolve entity — must be unambiguous
            resolved = await self.resolver.resolve_entity(entity_name, entity_type)
            if resolved.status == "pending_resolution":
                logger.debug(
                    "CacheGate MISS: entity '%s' is ambiguous (%.0f%% confidence)",
                    entity_name,
                    resolved.confidence,
                )
                return CacheResult(status="MISS")

            entity_id = resolved.node_id
            cutoff = self._freshness_cutoff(document_kind)

            # 2. Build metadata filter with server-side freshness
            collection_name = _pick_collection(document_kind)
            where_filter = {
                "$and": [
                    {"primary_entity_id": {"$eq": entity_id}},
                    {"source_type": {"$eq": document_kind}},
                    {"document_date": {"$gte": cutoff}},
                ]
            }
            # For run-scoped collections also filter by run_id
            if collection_name == "run_documents" and run_id:
                where_filter["$and"].append({"run_id": {"$eq": run_id}})

            # 3. Query Chroma — metadata-only, no semantic embedding needed
            collection = self.vs.get_collection(collection_name)
            results = await asyncio.to_thread(
                collection.get,
                where=where_filter,
            )

            docs: List[str] = results.get("documents") or []
            metas: List[dict] = results.get("metadatas") or []

            if not docs:
                logger.debug(
                    "CacheGate MISS: no cached chunks for entity=%s kind=%s",
                    entity_id,
                    document_kind,
                )
                return CacheResult(status="MISS")

            chunks_for_rerank = []
            for doc, meta in zip(docs, metas):
                chunks_for_rerank.append({"text": doc, "metadata": meta})

            if not goal_str:
                # Fast check for planning bypass; no reranking needed
                return CacheResult(status="HIT", chunks=None)

            formatted_document_blocks = await rerank_and_group_documents(
                chunks_for_rerank, goal_str, self.reranker
            )

            if not formatted_document_blocks:
                return CacheResult(status="MISS")

            logger.info(
                "CacheGate HIT: returned %d top documents for entity=%s kind=%s",
                len(formatted_document_blocks),
                entity_id,
                document_kind,
            )
            return CacheResult(status="HIT", chunks=formatted_document_blocks)

        except Exception as exc:
            # Never block the agent on a cache check error — default MISS
            logger.warning("CacheGate error (defaulting MISS): %s", exc)
            return CacheResult(status="MISS")


def _pick_collection(document_kind: str) -> str:
    """Maps a document_kind string to the correct Chroma collection name."""
    if document_kind in ("sanctions", "psc"):
        return "sanctions_entities"
    if document_kind == "historical_report":
        return "historical_reports"
    return "run_documents"

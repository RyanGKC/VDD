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

    def __init__(self, vector_store: VectorStore, entity_resolver: EntityResolver) -> None:
        self.vs = vector_store
        self.resolver = entity_resolver

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

            # 2. Build metadata filter
            filter_dict: dict = {
                "primary_entity_id": entity_id,
                "source_type": document_kind,
            }
            # For run-scoped collections also filter by run_id
            # (skip for persistent collections like sanctions / historical_reports)
            collection_name = _pick_collection(document_kind)
            if collection_name == "run_documents" and run_id:
                filter_dict["run_id"] = run_id

            if len(filter_dict) == 1:
                where_filter = filter_dict
            else:
                where_filter = {"$and": [{k: v} for k, v in filter_dict.items()]}

            # 3. Query Chroma — metadata-only, no semantic embedding needed
            collection = self.vs.get_collection(collection_name)
            results = await asyncio.to_thread(
                collection.get,
                where=where_filter,
                limit=10,
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

            # 4. Freshness filter — discard stale chunks
            fresh_docs = []
            cutoff_dt = datetime.fromisoformat(cutoff)
            for doc, meta in zip(docs, metas):
                chunk_date_str = meta.get("document_date", "")
                if chunk_date_str:
                    try:
                        chunk_date = datetime.fromisoformat(chunk_date_str)
                        if chunk_date.tzinfo is None:
                            chunk_date = chunk_date.replace(tzinfo=timezone.utc)
                        if chunk_date >= cutoff_dt:
                            fresh_docs.append(doc)
                    except ValueError:
                        pass

            if not fresh_docs:
                logger.debug(
                    "CacheGate MISS: all %d chunk(s) stale for entity=%s kind=%s",
                    len(docs),
                    entity_id,
                    document_kind,
                )
                return CacheResult(status="MISS")

            logger.info(
                "CacheGate HIT: %d fresh chunk(s) for entity=%s kind=%s",
                len(fresh_docs),
                entity_id,
                document_kind,
            )
            return CacheResult(status="HIT", chunks=fresh_docs)

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

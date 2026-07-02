import logging
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import uuid

from rag.vector_store import VectorStore
from rag.fingerprint import Fingerprinter
from rag.cache_gate import _pick_collection
from rag.entity_resolver import EntityResolver
from core.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

class ChunkTaggingResult(BaseModel):
    primary_entity_name: str
    mentioned_entities: List[str]
    relationship_context: str
    fiscal_period: Optional[str]

class IngestionPipeline:
    def __init__(self, vector_store: VectorStore, entity_resolver: EntityResolver, gemini: GeminiClient):
        self.vs = vector_store
        self.resolver = entity_resolver
        self.fingerprinter = Fingerprinter(self.vs)
        self.gemini = gemini
        self._inflight_fingerprints: set[str] = set()
        
        import asyncio
        import os
        from rag.rate_limiter import run_background_generation, run_background_embedding
        self.run_background_generation = run_background_generation
        self.run_background_embedding = run_background_embedding

    def chunk_text(self, text: str, chunk_size: int = 1500, overlap: int = 200) -> List[str]:
        """Simple structural chunking fallback"""
        # A more robust implementation would split by paragraphs/sections first
        paragraphs = text.split('\n\n')
        chunks = []
        current_chunk = ""
        for p in paragraphs:
            if len(current_chunk) + len(p) < chunk_size:
                current_chunk += p + "\n\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = p + "\n\n"
        if current_chunk:
            chunks.append(current_chunk.strip())
        return chunks

    async def ingest_document(
        self,
        text: str,
        source_url: str,
        source_type: str,
        run_id: str,
        source_tier: int = 3,
        document_date: str = None
    ) -> List[str]:
        if not document_date:
            document_date = datetime.now().isoformat()
            
        fingerprint = self.fingerprinter.fingerprint(source_url, document_date)
        
        collection_name = _pick_collection(source_type)
        if fingerprint in self._inflight_fingerprints or self.fingerprinter.document_exists(fingerprint, collection_name):
            logger.debug(f"Ingestion skipped: {source_url} already indexed or in-flight.")
            return []
            
        self._inflight_fingerprints.add(fingerprint)
        try:
            # 2. Chunking
            chunks = self.chunk_text(text)
            chunk_ids = []
            
            collection = self.vs.get_collection(collection_name)

            # 3. Entity & Temporal Tagging
            system_instruction = (
                "You are an entity extraction engine. For the given text passage, extract:\n"
                "1. The primary entity (company or person) the passage is about.\n"
                "2. Other mentioned entities.\n"
                "3. The relationship context (e.g., 'subsidiary_of', 'competitor_of', 'none').\n"
                "4. The fiscal period (e.g., 'FY2024') if applicable, else null."
            )

            batch_docs = []
            batch_metas = []
            batch_ids = []

            import asyncio
            async def _process_chunk(chunk: str):
                if not chunk.strip(): return None
                try:
                    # Wrap the LLM call with the background generation semaphore via coro factory
                    tagging = await self.run_background_generation(
                        lambda: self.gemini.generate_structured(
                            system_instruction=system_instruction,
                            prompt=f"Passage: {chunk}",
                            schema=ChunkTaggingResult,
                        )
                    )
                    
                    resolved_primary = await self.resolver.resolve_entity(tagging.primary_entity_name)
                    primary_entity_id = resolved_primary.node_id if resolved_primary.status != "pending_resolution" else "pending_resolution"
                        
                    metadata = {
                        "primary_entity_id": primary_entity_id or tagging.primary_entity_name,
                        "mentioned_entities": ",".join(tagging.mentioned_entities),
                        "relationship_context": tagging.relationship_context,
                        "document_date": document_date,
                        "fiscal_period": tagging.fiscal_period or "",
                        "source_tier": source_tier,
                        "source_type": source_type,
                        "document_fingerprint": fingerprint,
                        "run_id": run_id
                    }
                    return (chunk, metadata, str(uuid.uuid4()))
                except Exception as e:
                    logger.error(f"Error tagging chunk: {e}")
                    return None

            results = await asyncio.gather(*[_process_chunk(c) for c in chunks])
            for res in results:
                if res:
                    c, m, i = res
                    batch_docs.append(c)
                    batch_metas.append(m)
                    batch_ids.append(i)
                    chunk_ids.append(i)

            if batch_docs:
                import asyncio
                
                # Chroma collection.add makes a synchronous network call to Vertex AI Embeddings.
                # Wrap it in run_background_embedding and run it in a threadpool to prevent blocking the event loop.
                def _do_embed_and_add():
                    collection.add(
                        documents=batch_docs,
                        metadatas=batch_metas,
                        ids=batch_ids
                    )
                
                await self.run_background_embedding(
                    lambda: asyncio.to_thread(_do_embed_and_add)
                )

            return chunk_ids
        finally:
            self._inflight_fingerprints.discard(fingerprint)

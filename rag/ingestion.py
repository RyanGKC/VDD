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
from rag.mention_index import init_mention_index, record_mentions

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
        self.mention_conn = init_mention_index()
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
                
                # Carry over the trailing `overlap` characters from the flushed chunk
                if overlap > 0 and len(current_chunk) > overlap:
                    overlap_text = current_chunk[-overlap:]
                    # Try to snap to a sentence boundary, fallback to word boundary
                    boundary = overlap_text.find('. ')
                    if boundary == -1:
                        boundary = overlap_text.find(' ')
                        
                    if boundary != -1:
                        overlap_text = overlap_text[boundary+1:].lstrip()
                        
                    current_chunk = overlap_text + " " + p + "\n\n"
                else:
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
            
            import asyncio
            from rag.segmentation import segment_chunks
            
            # 1. Embed all chunks first to drive segmentation
            chunk_embeddings = await self.run_background_embedding(
                lambda: self.gemini.embed_content(chunks)
            )
            
            # 2. Segment chunks by semantic similarity and entity drift
            segments = segment_chunks(chunks, chunk_embeddings)

            # 3. Entity & Temporal Tagging (Run ONCE per semantic segment)
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
            batch_embeddings = []

            async def _process_segment(segment_indices: List[int]):
                segment_texts = [chunks[i] for i in segment_indices]
                full_text = "\n\n".join(segment_texts)
                if len(full_text) > 6000:
                    full_text = full_text[:3000] + "\n\n...\n\n" + full_text[-3000:]
                    
                try:
                    tagging = await self.run_background_generation(
                        lambda: self.gemini.generate_structured(
                            system_instruction=system_instruction,
                            prompt=f"Passage: {full_text}",
                            schema=ChunkTaggingResult,
                        )
                    )
                    
                    resolved_primary = await self.resolver.resolve_entity(tagging.primary_entity_name)
                    primary_entity_id = resolved_primary.node_id if resolved_primary.status != "pending_resolution" else "pending_resolution"
                    
                    # Resolve mentioned entities
                    resolved_mentions = await asyncio.gather(
                        *[self.resolver.resolve_entity(m) for m in tagging.mentioned_entities],
                        return_exceptions=True
                    )
                    canonical_mention_ids = []
                    for rm in resolved_mentions:
                        if not isinstance(rm, Exception) and rm.status != "pending_resolution" and rm.node_id:
                            canonical_mention_ids.append(rm.node_id)
                        
                    shared_metadata = {
                        "primary_entity_id": primary_entity_id or tagging.primary_entity_name,
                        "mentioned_entities": ",".join(tagging.mentioned_entities),
                        "relationship_context": tagging.relationship_context,
                        "document_date": document_date,
                        "fiscal_period": tagging.fiscal_period or "",
                        "source_tier": source_tier,
                        "source_type": source_type,
                        "document_fingerprint": fingerprint,
                        "source_url": source_url,
                        "run_id": run_id
                    }
                    
                    processed_items = []
                    for idx in segment_indices:
                        # Clone metadata to add the unique chunk_index
                        meta = dict(shared_metadata)
                        meta["chunk_index"] = idx
                        chunk_id = str(uuid.uuid4())
                        processed_items.append((chunks[idx], meta, chunk_id, chunk_embeddings[idx]))
                        
                        # Record secondary mentions for this chunk in SQLite
                        if canonical_mention_ids:
                            record_mentions(self.mention_conn, chunk_id, canonical_mention_ids)
                            
                    return processed_items
                except Exception as e:
                    logger.error(f"Error tagging segment: {e}")
                    return []

            results = await asyncio.gather(*[_process_segment(seg) for seg in segments])
            for res_group in results:
                for c, m, i, emb in res_group:
                    batch_docs.append(c)
                    batch_metas.append(m)
                    batch_ids.append(i)
                    batch_embeddings.append(emb)
                    chunk_ids.append(i)

            if batch_docs:
                def _do_embed_and_add():
                    # Pass the pre-computed embeddings directly to ChromaDB
                    collection.add(
                        documents=batch_docs,
                        metadatas=batch_metas,
                        ids=batch_ids,
                        embeddings=batch_embeddings
                    )
                
                # We do not need run_background_embedding here since we are just doing local I/O
                # collection.add with explicit embeddings does not hit the Vertex API
                await asyncio.to_thread(_do_embed_and_add)

            return chunk_ids
        finally:
            self._inflight_fingerprints.discard(fingerprint)

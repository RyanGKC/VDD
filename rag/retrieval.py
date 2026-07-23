import asyncio
import logging
from typing import List, Dict, Optional
from pydantic import BaseModel

from rag.vector_store import VectorStore
from rag.entity_resolver import EntityResolver
from rag.rerank import Reranker
from core.neo4j_client import Neo4jClient
from rag.mention_index import init_mention_index, get_chunks_mentioning

logger = logging.getLogger(__name__)

class RetrievalResult(BaseModel):
    primary: List[str]
    primary_sources: List[str]
    primary_ids: List[str] = []
    related: Dict[str, List[str]]
    related_ids: Dict[str, List[str]] = {}

class RetrievalEngine:
    def __init__(self, vector_store: VectorStore, entity_resolver: EntityResolver, reranker: Reranker, neo4j: Neo4jClient):
        self.vs = vector_store
        self.resolver = entity_resolver
        self.reranker = reranker
        self.neo4j = neo4j
        self.mention_conn = init_mention_index()

    async def _query_chroma(self, collection_name: str, query: str, where_filter: dict, top_k: int) -> tuple[List[str], List[dict], List[str]]:
        collection = self.vs.get_collection(collection_name)
        results = await asyncio.to_thread(
            collection.query,
            query_texts=[query],
            n_results=top_k,
            where=where_filter
        )
        if not results.get("documents") or not results["documents"][0]:
            return [], [], []
        metadatas = results.get("metadatas")
        ids = results.get("ids")
        meta = metadatas[0] if metadatas and metadatas[0] else [{}] * len(results["documents"][0])
        chunk_ids = ids[0] if ids and ids[0] else [""] * len(results["documents"][0])
        return results["documents"][0], meta, chunk_ids

    async def retrieve(
        self,
        query: str,
        entity_name: str,
        entity_type: str,
        collection_name: str,
        fiscal_period: Optional[str] = None,
        include_related: Optional[List[str]] = None,
        top_k: int = 5,
        run_id: Optional[str] = None
    ) -> RetrievalResult:
        
        # 1. Resolve primary entity
        resolved = await self.resolver.resolve_entity(entity_name, entity_type)
        if resolved.status == "pending_resolution":
            raise ValueError(f"Entity '{entity_name}' is ambiguous (confidence: {resolved.confidence}). Escalation required.")
        
        primary_id = resolved.node_id
        
        # 2. Build metadata filter
        filter_dict = {"primary_entity_id": primary_id}
        if run_id and collection_name == "run_documents":
            filter_dict["run_id"] = run_id
        if fiscal_period:
            filter_dict["fiscal_period"] = fiscal_period

        if len(filter_dict) == 1:
            where_filter = filter_dict
        else:
            where_filter = {"$and": [{k: v} for k, v in filter_dict.items()]}

        # 3. Retrieve primary chunks
        primary_chunks, primary_metas, primary_chunk_ids = await self._query_chroma(collection_name, query, where_filter, top_k)
        
        # 3b. Retrieve mention chunks
        mention_ids = get_chunks_mentioning(self.mention_conn, primary_id)
        if mention_ids:
            collection = self.vs.get_collection(collection_name)
            # collection.get() may not support huge lists of ids, but typically it's fine.
            # We filter by run_id if applicable.
            mention_results = await asyncio.to_thread(collection.get, ids=mention_ids)
            mention_docs = mention_results.get("documents") or []
            mention_metas = mention_results.get("metadatas") or []
            mention_ids_list = mention_results.get("ids") or []
            
            # Combine and deduplicate
            primary_set = set(primary_chunks)
            for doc, meta, cid in zip(mention_docs, mention_metas, mention_ids_list):
                if doc not in primary_set:
                    primary_chunks.append(doc)
                    primary_metas.append(meta)
                    primary_chunk_ids.append(cid)
                    primary_set.add(doc)
        
        # 4. Re-rank primary chunks
        primary_sources = []
        final_primary_ids = []
        if primary_chunks:
            assessments = await self.reranker.assess_chunks(primary_chunks, query)
            scored = [
                (primary_chunks[a.index], primary_metas[a.index], primary_chunk_ids[a.index], a.score)
                for a in assessments
                if a.is_relevant
            ]
            scored.sort(key=lambda x: x[3], reverse=True)
            primary_chunks = [chunk for chunk, meta, cid, _ in scored]
            primary_sources = [meta.get("source_url") or "unknown" for chunk, meta, cid, _ in scored]
            final_primary_ids = [cid for chunk, meta, cid, _ in scored]
            
        result = RetrievalResult(primary=primary_chunks, primary_sources=primary_sources, primary_ids=final_primary_ids, related={})
        
        # 5. Include related (Neo4j traversal)
        if include_related and self.neo4j.driver:
            async with self.neo4j.driver.session() as session:
                for rel_type in include_related:
                    # Safely construct the relationship pattern
                    valid_rels = [rel_type] if rel_type.replace('_', '').isalnum() else []
                    rel_pattern = ""
                    if valid_rels:
                        rel_pattern = ":" + "|".join(valid_rels)
                        
                    cypher = f"""
                    MATCH (n)-[{rel_pattern}]-(c:Company {{name: $name}})
                    RETURN n.name AS related_name LIMIT 3
                    """
                    db_res = await session.run(cypher, name=primary_id)
                    related_nodes = await db_res.data()
                    
                    related_chunks_for_type = []
                    related_ids_for_type = []
                    for row in related_nodes:
                        rel_name = row.get("related_name")
                        if not rel_name:
                            continue
                            
                        # Retrieve for related entity
                        rel_resolved = await self.resolver.resolve_entity(rel_name, "company")
                        if rel_resolved.status == "pending_resolution":
                            continue
                            
                        rel_filter = {"primary_entity_id": rel_resolved.node_id}
                        if run_id and collection_name == "run_documents":
                            rel_filter["run_id"] = run_id
                            
                        if len(rel_filter) == 1:
                            rel_where = rel_filter
                        else:
                            rel_where = {"$and": [{k: v} for k, v in rel_filter.items()]}
                            
                        rel_chunks, _, rel_ids = await self._query_chroma(collection_name, query, rel_where, top_k=2)
                        if rel_chunks:
                            # Re-rank for the related entity against the original query
                            assessments = await self.reranker.assess_chunks(rel_chunks, query)
                            scored_rel = [
                                (rel_chunks[a.index], rel_ids[a.index], a.score)
                                for a in assessments
                                if a.is_relevant
                            ]
                            scored_rel.sort(key=lambda x: x[2], reverse=True)
                            rel_chunks = [chunk for chunk, cid, _ in scored_rel]
                            rel_ids_filtered = [cid for chunk, cid, _ in scored_rel]
                            # Prefix with explicit context so agent doesn't flatten
                            for rc, cid in zip(rel_chunks, rel_ids_filtered):
                                related_chunks_for_type.append(f"[Data for {rel_type} '{rel_name}']: {rc}")
                                related_ids_for_type.append(cid)
                                
                    if related_chunks_for_type:
                        result.related[rel_type] = related_chunks_for_type
                        result.related_ids[rel_type] = related_ids_for_type

        return result

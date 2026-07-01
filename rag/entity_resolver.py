from typing import Dict, Any, Optional
from pydantic import BaseModel
from rapidfuzz import fuzz
from core.neo4j_client import Neo4jClient
import logging

logger = logging.getLogger(__name__)

class ResolvedEntity(BaseModel):
    node_id: Optional[str]  # The canonical name/id in Neo4j
    confidence: float
    status: str  # "resolved" | "pending_resolution" | "new"

class EntityResolver:
    def __init__(self, neo4j_client: Neo4jClient):
        self.neo4j = neo4j_client
        self.cache: Dict[str, ResolvedEntity] = {}

    async def resolve_entity(self, name: str, entity_type: str = "company", threshold: float = 85.0, run_id: str = None) -> ResolvedEntity:
        """
        Resolves an entity name to a canonical Neo4j node ID.
        Queries Neo4j first for an exact/alias match, then fuzzy match.
        Returns 'pending_resolution' if confidence is too low.
        """
        cache_key = f"{run_id}:{entity_type}:{name}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        if not self.neo4j.driver:
            # Fallback if no neo4j
            res = ResolvedEntity(node_id=name, confidence=100.0, status="new")
            self.cache[cache_key] = res
            return res

        label = "Company" if entity_type.lower() == "company" else "Person"

        # 1. Exact or Alias Match via Full-Text Index
        # We query the fulltext index 'entity_names'
        exact_query = f"""
        CALL db.index.fulltext.queryNodes("entity_names", $query)
        YIELD node, score
        WHERE '{label}' IN labels(node)
        RETURN node.name AS name, score
        LIMIT 5
        """
        
        # We also want to just do a direct match just in case
        direct_query = f"""
        MATCH (n:{label})
        WHERE n.name = $name OR $name IN n.aliases OR n.canonical_name = $name
        RETURN n.name AS name
        LIMIT 1
        """

        try:
            async with self.neo4j.driver.session() as session:
                # Try direct exact match first
                result = await session.run(direct_query, name=name)
                record = await result.single()
                if record:
                    res = ResolvedEntity(node_id=record["name"], confidence=100.0, status="resolved")
                    self.cache[cache_key] = res
                    return res
                
                # Try full-text index first before downloading everything
                ft_result = await session.run(exact_query, query=name)
                ft_records = await ft_result.data()
                
                best_match = None
                best_score = 0.0
                
                if ft_records:
                    for r in ft_records:
                        candidate_name = r.get("name", "")
                        fuzz_score = fuzz.ratio(name.lower(), candidate_name.lower())
                        if fuzz_score > best_score:
                            best_score = fuzz_score
                            best_match = candidate_name
                            
                # Fallback: Fetch all names to do python-side fuzzy match ONLY if full-text failed
                if not best_match or best_score < threshold:
                    all_query = f"MATCH (n:{label}) RETURN n.name AS name, n.aliases AS aliases"
                    all_result = await session.run(all_query)
                    records = await all_result.data()
                    
                    for r in records:
                        candidate_name = r.get("name", "")
                        score = fuzz.ratio(name.lower(), candidate_name.lower())
                        if score > best_score:
                            best_score = score
                            best_match = candidate_name
                            
                        for alias in (r.get("aliases") or []):
                            alias_score = fuzz.ratio(name.lower(), alias.lower())
                            if alias_score > best_score:
                                best_score = alias_score
                                best_match = candidate_name
                
                if best_match and best_score >= threshold:
                    res = ResolvedEntity(node_id=best_match, confidence=best_score, status="resolved")
                    self.cache[cache_key] = res
                    return res
                elif best_score > 0 and best_score >= 60.0: # Ambiguous
                    res = ResolvedEntity(node_id=None, confidence=best_score, status="pending_resolution")
                    self.cache[cache_key] = res
                    return res
                else:
                    # No match found, safe to create new
                    res = ResolvedEntity(node_id=name, confidence=100.0, status="new")
                    self.cache[cache_key] = res
                    return res

        except Exception as e:
            logger.error(f"Error resolving entity {name}: {e}")
            res = ResolvedEntity(node_id=name, confidence=100.0, status="new")
            self.cache[cache_key] = res
            return res

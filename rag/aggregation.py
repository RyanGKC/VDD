import logging
from typing import Dict, List, Literal, Any
from pydantic import BaseModel
from core.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)

class AggregationResult(BaseModel):
    computed_total: float
    breakdown: Dict[str, float]
    operation: str
    metric: str
    missing_entities: List[str]

class Aggregator:
    def __init__(self, neo4j: Neo4jClient):
        self.neo4j = neo4j

    async def aggregate_across_entities(
        self,
        root_entity_name: str,
        relationship: str,       # e.g. "SUBSIDIARY_OF"
        metric: str,              # e.g. "total_debt"
        operation: Literal["sum", "avg", "max"],
        entity_values_cache: Dict[str, Dict[str, float]] # Pre-fetched structured data by agent
    ) -> AggregationResult:
        """
        Calculates aggregations deterministically across related entities.
        The entity_values_cache must contain the pre-fetched structured metrics per entity name.
        """
        if not self.neo4j.driver:
            raise RuntimeError("Neo4j driver not initialized.")
            
        # 1. Identify relevant entity set
        # We find nodes with the requested relationship pointing TO or FROM the target
        # For a standard parent-child like (c)-[:SUBSIDIARY_OF]->(root)
        cypher = f"""
        MATCH (c)-[:{relationship}]->(root:Company {{name: $name}})
        RETURN c.name AS related_name
        """
        
        async with self.neo4j.driver.session() as session:
            result = await session.run(cypher, name=root_entity_name)
            records = await result.data()
            
        related_entities = [r["related_name"] for r in records if r.get("related_name")]
        
        # Include the root entity itself in the aggregation if it has data
        entities_to_aggregate = [root_entity_name] + related_entities
        
        breakdown = {}
        missing = []
        valid_values = []
        
        # 2. Retrieve structured values
        for entity in entities_to_aggregate:
            metrics = entity_values_cache.get(entity, {})
            val = metrics.get(metric)
            if val is not None:
                try:
                    v = float(val)
                    breakdown[entity] = v
                    valid_values.append(v)
                except ValueError:
                    missing.append(entity)
            else:
                missing.append(entity)
                
        # 3. Perform calculation
        computed_total = 0.0
        if valid_values:
            if operation == "sum":
                computed_total = sum(valid_values)
            elif operation == "avg":
                computed_total = sum(valid_values) / len(valid_values)
            elif operation == "max":
                computed_total = max(valid_values)
                
        return AggregationResult(
            computed_total=computed_total,
            breakdown=breakdown,
            operation=operation,
            metric=metric,
            missing_entities=missing
        )

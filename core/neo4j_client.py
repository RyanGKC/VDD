import os
import logging
from neo4j import AsyncGraphDatabase
from google import genai
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class Neo4jClient:
    def __init__(self):
        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "password")
        try:
            self.driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        except Exception as e:
            logger.warning(f"Failed to initialize Neo4j driver (Graph database features will be disabled): {e}")
            self.driver = None
            
        from core.gemini_client import GeminiClient
        self.gemini_client = GeminiClient()

    async def get_embedding(self, text: str) -> List[float]:
        res = await self.gemini_client.embed_content([text])
        return res[0]

    async def close(self):
        if self.driver:
            await self.driver.close()

    async def setup_constraints(self):
        if not self.driver:
            return
        constraint_company = "CREATE CONSTRAINT company_name IF NOT EXISTS FOR (c:Company) REQUIRE c.name IS UNIQUE"
        constraint_person = "CREATE CONSTRAINT person_name IF NOT EXISTS FOR (p:Person) REQUIRE p.name IS UNIQUE"
        vector_query = """
        CREATE VECTOR INDEX company_embeddings IF NOT EXISTS 
        FOR (c:Company) ON (c.embedding) 
        OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}
        """
        fulltext_query = """
        CREATE FULLTEXT INDEX entity_names IF NOT EXISTS 
        FOR (n:Company|Person) ON EACH [n.name, n.canonical_name, n.aliases]
        """
        try:
            async with self.driver.session() as session:
                await session.run(constraint_company)
                await session.run(constraint_person)
                try:
                    await session.run(vector_query)
                except Exception as ve:
                    if "EquivalentSchemaRuleAlreadyExists" not in str(ve):
                        raise ve
                try:
                    await session.run(fulltext_query)
                except Exception as fe:
                    if "EquivalentSchemaRuleAlreadyExists" not in str(fe):
                        raise fe
        except Exception as e:
            logger.warning(f"Failed to setup Neo4j constraints or indexes: {e}")

    async def save_company_node(self, company_name: str, risk_score: str):
        if not self.driver:
            return
        
        try:
            embedding = await self.get_embedding(company_name)
        except Exception as e:
            logger.error(f"Failed to generate embedding for {company_name}: {e}")
            embedding = []

        query = """
        MERGE (c:Company {name: $name})
        SET c.overall_risk = $risk
        WITH c
        CALL db.create.setNodeVectorProperty(c, 'embedding', $embedding)
        RETURN c
        """
        try:
            async with self.driver.session() as session:
                await session.run(query, name=company_name, risk=risk_score, embedding=embedding)
        except Exception as e:
            logger.error(f"Failed to save node {company_name} to Neo4j: {e}")

    async def find_similar_company(self, company_name: str, threshold: float = 0.90) -> Optional[str]:
        if not self.driver:
            return None
            
        try:
            embedding = await self.get_embedding(company_name)
        except Exception:
            return None
            
        query = """
        CALL db.index.vector.queryNodes('company_embeddings', 1, $embedding)
        YIELD node, score
        WHERE score >= $threshold
        RETURN node.name AS name, score
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(query, embedding=embedding, threshold=threshold)
                record = await result.single()
                if record:
                    return record["name"]
        except Exception as e:
            logger.error(f"Failed to query similar company for {company_name}: {e}")
            
        return None

    async def get_risky_neighbors(self, company_name: str, max_hops: int = 2) -> List[Dict]:
        if not self.driver:
            return []
            
        # Matches paths up to max_hops away where the connected node has a high/critical risk
        query = """
        MATCH (start:Company {name: $name})-[*1..2]-(connected:Company)
        WHERE connected.overall_risk IN ['high', 'critical']
        RETURN DISTINCT connected.name AS name, connected.overall_risk AS risk
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(query, name=company_name)
                records = await result.data()
                return records
        except Exception as e:
            logger.error(f"Failed to query risky neighbors for {company_name}: {e}")
            return []

    async def save_supply_edge(self, supplier_name: str, target_company: str):
        if not self.driver:
            return
        query = """
        MERGE (supplier:Company {name: $supplier})
        MERGE (target:Company {name: $target})
        MERGE (supplier)-[:SUPPLIES_TO]->(target)
        """
        try:
            async with self.driver.session() as session:
                await session.run(query, supplier=supplier_name, target=target_company)
        except Exception as e:
            logger.error(f"Failed to save edge {supplier_name}->{target_company} to Neo4j: {e}")

    async def save_ownership_edge(self, parent_name: str, target_company: str):
        if not self.driver:
            return
        query = """
        MERGE (parent:Company {name: $parent})
        MERGE (target:Company {name: $target})
        MERGE (parent)-[:OWNS]->(target)
        """
        try:
            async with self.driver.session() as session:
                await session.run(query, parent=parent_name, target=target_company)
        except Exception as e:
            logger.error(f"Failed to save edge {parent_name}->{target_company} to Neo4j: {e}")

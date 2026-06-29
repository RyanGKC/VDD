import os
import logging
from neo4j import AsyncGraphDatabase

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

    async def close(self):
        if self.driver:
            await self.driver.close()

    async def setup_constraints(self):
        if not self.driver:
            return
        query = "CREATE CONSTRAINT company_name IF NOT EXISTS FOR (c:Company) REQUIRE c.name IS UNIQUE"
        try:
            async with self.driver.session() as session:
                await session.run(query)
        except Exception as e:
            logger.warning(f"Failed to setup Neo4j constraints: {e}")

    async def save_company_node(self, company_name: str, risk_score: str):
        if not self.driver:
            return
        query = """
        MERGE (c:Company {name: $name})
        SET c.overall_risk = $risk
        RETURN c
        """
        try:
            async with self.driver.session() as session:
                await session.run(query, name=company_name, risk=risk_score)
        except Exception as e:
            logger.error(f"Failed to save node {company_name} to Neo4j: {e}")

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

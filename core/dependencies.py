from rag.vector_store import VectorStore
from core.neo4j_client import Neo4jClient
from core.gemini_client import GeminiClient
from rag.entity_resolver import EntityResolver
from rag.rerank import Reranker
from rag.retrieval import RetrievalEngine
from rag.ingestion import IngestionPipeline
from rag.cache_gate import CacheGate
from rag.singleflight import SingleFlight
from rag.background_tasks import BackgroundTaskRegistry
import httpx
import os

# Global Singletons to prevent resource leaks (BUG-3)
vs = VectorStore()
neo4j = Neo4jClient()
gemini = GeminiClient()

# Opt 5: Faster/cheaper model for simple entity extraction/tagging
tagging_gemini = GeminiClient(model=os.getenv("GEMINI_TAGGING_MODEL", "gemini-2.5-flash-lite"))

# Opt 3: Shared HTTP client to reuse connections across all agents
http_client = httpx.AsyncClient(timeout=15.0, limits=httpx.Limits(max_connections=20))

# Core RAG components
resolver = EntityResolver(neo4j)
reranker = Reranker(gemini)

retrieval_engine = RetrievalEngine(vs, resolver, reranker, neo4j)
ingestion_pipeline = IngestionPipeline(vs, resolver, tagging_gemini)

# Async orchestration layer
cache_gate = CacheGate(vs, resolver)
singleflight = SingleFlight()
background_tasks = BackgroundTaskRegistry()

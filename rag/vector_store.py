import os
import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
from google import genai
import logging
from pathlib import Path
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

class GeminiEmbeddingFunction(EmbeddingFunction):
    def __init__(self):
        from core.gemini_client import get_shared_client
        self.client = get_shared_client()
        self.model = "text-embedding-004"
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        reraise=True,
    )
    def __call__(self, input: Documents) -> Embeddings:
        from core.gemini_client import ensure_valid_token_sync
        ensure_valid_token_sync()
        response = self.client.models.embed_content(
            model=self.model,
            contents=input
        )
        return [e.values for e in response.embeddings]


class VectorStore:
    def __init__(self):
        # We use a PersistentClient so sanctions and historical reports persist.
        # run_documents will be scoped by run_id metadata.
        self.client = chromadb.PersistentClient(path="./chroma_db")
        self.embedding_fn = GeminiEmbeddingFunction()
        
        # 1. Ephemeral/run-scoped documents
        self.run_documents = self.client.get_or_create_collection(
            name="run_documents",
            embedding_function=self.embedding_fn
        )
        
        # 2. Persistent sanctions entities
        self.sanctions_entities = self.client.get_or_create_collection(
            name="sanctions_entities",
            embedding_function=self.embedding_fn
        )
        
        # 3. Persistent historical reports
        self.historical_reports = self.client.get_or_create_collection(
            name="historical_reports",
            embedding_function=self.embedding_fn
        )

    def get_collection(self, collection_name: str):
        if collection_name == "run_documents":
            return self.run_documents
        elif collection_name == "sanctions_entities":
            return self.sanctions_entities
        elif collection_name == "historical_reports":
            return self.historical_reports
        else:
            raise ValueError(f"Unknown collection: {collection_name}")

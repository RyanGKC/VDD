import os
import uuid
from typing import List, Dict, Any
import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
from google import genai
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load local environment variables from core/.env if available
env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

class GeminiEmbeddingFunction(EmbeddingFunction):
    def __init__(self):
        use_vertex = os.getenv("GOOGLE_GENAI_USE_ENTERPRISE", "false").lower() == "true"
        if use_vertex:
            project = os.getenv("GOOGLE_CLOUD_PROJECT")
            location = os.getenv("GOOGLE_CLOUD_LOCATION")
            self.client = genai.Client(vertexai=True, project=project, location=location)
        else:
            self.client = genai.Client()
            
        self.model = "text-embedding-004"
        
    def __call__(self, input: Documents) -> Embeddings:
        response = self.client.models.embed_content(
            model=self.model,
            contents=input
        )
        # response.embeddings is a list of EmbedContentResponse items
        return [e.values for e in response.embeddings]


class DocumentStore:
    def __init__(self, run_id: str = "default"):
        # Ephemeral in-memory client
        self.client = chromadb.Client()
        self.collection_name = f"run_{run_id.replace('-', '_')}"
        
        try:
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=GeminiEmbeddingFunction()
            )
            logger.info(f"Initialized DocumentStore collection: {self.collection_name}")
        except Exception as e:
            logger.error(f"Failed to initialize Chroma collection {self.collection_name}: {e}")
            self.collection = None

    def chunk_text(self, text: str, chunk_size: int = 1500, overlap: int = 200) -> List[str]:
        """Simple text chunker by character count."""
        chunks = []
        start = 0
        text_length = len(text)
        
        while start < text_length:
            end = min(start + chunk_size, text_length)
            chunks.append(text[start:end])
            start += chunk_size - overlap
            
        return chunks

    def add_document(self, text: str, metadata: Dict[str, Any] = None):
        """Chunks a document and adds it to the vector store."""
        if not self.collection or not text.strip():
            return

        chunks = self.chunk_text(text)
        if not chunks:
            return

        ids = [str(uuid.uuid4()) for _ in chunks]
        metadatas = [metadata or {} for _ in chunks]
        
        try:
            self.collection.add(
                documents=chunks,
                metadatas=metadatas,
                ids=ids
            )
        except Exception as e:
            logger.error(f"Error adding document to Chroma: {e}")

    def query(self, query_text: str, n_results: int = 3) -> List[str]:
        """Queries the vector store and returns the most relevant text chunks."""
        if not self.collection:
            return []
            
        try:
            results = self.collection.query(
                query_texts=[query_text],
                n_results=n_results
            )
            if results and "documents" in results and results["documents"]:
                return results["documents"][0]
            return []
        except Exception as e:
            logger.error(f"Error querying Chroma: {e}")
            return []

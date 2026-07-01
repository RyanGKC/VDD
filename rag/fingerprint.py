import hashlib
from typing import List
from rag.vector_store import VectorStore

class Fingerprinter:
    def __init__(self, vector_store: VectorStore):
        self.vs = vector_store

    @staticmethod
    def fingerprint(source_url: str, fetch_date: str) -> str:
        """Generates a SHA256 hex digest for a document based on its URL."""
        # fetch_date is intentionally omitted from the hash to allow deduplication across runs
        data = f"{source_url}".encode('utf-8')
        return hashlib.sha256(data).hexdigest()
        
    def document_exists(self, fingerprint: str, collection_name: str) -> bool:
        """Checks if any chunks with this fingerprint exist in the given collection."""
        collection = self.vs.get_collection(collection_name)
        results = collection.get(
            where={"document_fingerprint": fingerprint},
            limit=1
        )
        return len(results.get("ids", [])) > 0
        
    def get_cached_chunks(self, fingerprint: str, collection_name: str) -> List[str]:
        """Returns all cached chunks for a given fingerprint."""
        collection = self.vs.get_collection(collection_name)
        results = collection.get(
            where={"document_fingerprint": fingerprint}
        )
        return results.get("documents", [])

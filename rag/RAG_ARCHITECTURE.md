# VDD RAG & Caching Architecture

This document outlines the architecture, flow, and component interactions of the Retrieval-Augmented Generation (RAG) and caching system within the VDD Prototype.

## 1. Overview of Agent Interaction

Agents in this system do not query the web or the RAG system directly. Instead, they rely on the `generate_with_web_search()` method found in `base_agent.py`. This method acts as a sophisticated orchestrator that routes data through a multi-phase cache and RAG pipeline.

The RAG system serves a dual purpose:
1. **Cache Bypass (Fast Path)**: Completely replacing an external web search by serving fresh, relevant, pre-indexed documents.
2. **Post-Fetch Distillation**: Augmenting a live web search with highly targeted context (e.g., historical data or related entity data) without overwhelming the LLM's context window.

## 2. When is the RAG Architecture Used? (The 4-Phase Flow)

For every search query planned by an agent, the system executes the following phases:

### Phase A: Pre-fetch Planning Check (Fast Path)
Before an agent even plans its web searches, it queries `CacheGate.check(goal_str="")`. 
- **Action**: This does a fast, metadata-only check in ChromaDB to see if fresh chunks exist for the entity.
- **Outcome**: If a `HIT` occurs, the agent skips its expensive LLM-based query planning phase and uses default queries, knowing the cache will catch them.

### Phase B: Fetch and Cache Gate
For each planned query, the orchestrator asks the CacheGate if the data is already available locally.
- **Action**: `CacheGate.check(goal_str="<actual goal>")` executes.
- **HIT**: CacheGate returns fully reranked, intact documents. The external web search is skipped entirely.
- **MISS**: The system proceeds to `SingleFlight`. `SingleFlight` deduplicates concurrent network requests; if multiple agents request the same search, only the "leader" makes the API call, and the "followers" reuse the result.

### Phase C: Background Ingestion
Once the leader fetches new raw data from the web, it is immediately scheduled for indexing.
- **Action**: `BackgroundTaskRegistry` spins up an asynchronous task using `IngestionPipeline`.
- **Flow**: The raw text is chunked $\rightarrow$ embedded via Gemini (`text-embedding-004`) $\rightarrow$ segmented by semantic similarity and entity drift $\rightarrow$ tagged by an LLM (one call per segment) $\rightarrow$ resolved to canonical Neo4j entity IDs $\rightarrow$ inserted into ChromaDB.
- **Note**: The agent does not wait for this to finish; ingestion is strictly fire-and-forget on the critical path.

### Phase D: RAG Distillation (Retrieval Engine)
After the raw data is fetched (but before the final agent analysis), the `RetrievalEngine` is invoked to provide a focused context window.
- **Action**: `RetrievalEngine.retrieve()` searches ChromaDB for highly relevant historical or relational chunks to augment the raw web data.
- **Outcome**: The agent's final prompt includes both the raw web fetch results and the distilled RAG context.

---

## 3. How Searching and Reranking Works

The system uses two distinctly different strategies for searching and returning documents depending on whether it is serving a Cache hit or Distilling context. Both systems now rely on a **Unified LLM Assessor** (`assess_chunks()`), which in a single LLM call evaluates chunks and returns both a **binary relevance verdict** (`is_relevant`) and a **numeric score** (1–10). The assessor is designed to fail-closed: if the LLM omits a chunk or throws an exception, the chunk is marked `is_relevant=False` with a score of `0.0`.

### CacheGate (Document-Level Retrieval)
- **Search Mechanism**: Uses a **metadata-only filter** (`collection.get()`). It filters by `entity_id`, `source_type`, and a `freshness_cutoff` (e.g., news from the last 24h). It does **not** perform a vector semantic search.
- **Filtering & Reranking**: All retrieved chunks are passed to the unified LLM assessor. Documents that contain zero relevant chunks are dropped entirely. Surviving eligible documents are then ranked by the score of their *single highest-scoring relevant chunk*. 
- **Formatting**: It retains the top 5 highest-scoring documents. It reassembles each winning document in its original reading order (`chunk_index`). Crucially, it uses an **overlap-aware merge** (`_merge_chunks_deoverlap()`) to detect and strip the ~200-character trailing overlap that the ingestion pipeline carries forward between consecutive chunks, avoiding duplicated sentences in the LLM's context window.

### RetrievalEngine (Chunk-Level Distillation)
- **Search Mechanism**: Uses a **semantic vector search** (`collection.query()`) to find the top $K$ (default 4) most similar chunks to the agent's goal.
- **Mention Augmentation**: It checks a SQLite `MentionIndex` to include chunks that mention the target entity secondarily.
- **Filtering & Reranking**: It passes the retrieved chunks through the same unified LLM assessor. Irrelevant chunks are dropped, and the surviving chunks are sorted by their 1–10 numeric score (descending).
- **Graph Traversal**: (Opt-in) It can traverse Neo4j to pull chunks belonging to related entities (e.g., subsidiaries).

---

## 4. What is Returned to the Agents?

The difference in what these two systems return is a deliberate design choice reflecting their roles:

- **CacheGate Returns Whole Documents**: Because CacheGate *replaces* the web search entirely on a HIT, the agent needs full context. It returns up to 5 whole documents, with chunks stitched together in their original order.
- **RetrievalEngine Returns Targeted Chunks**: Because the RetrievalEngine *augments* an already-large raw web search payload, it must be extremely token-efficient. It returns only individual, highly targeted chunks (up to 4) to provide the sharpest needle from the haystack without overwhelming the context window.

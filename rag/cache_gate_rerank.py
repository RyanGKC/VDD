"""
cache_gate_rerank.py — Score-based document selection for CacheGate HITs.

Pipeline:
  1. assess_chunks()  → produces is_relevant verdict + score (1-10) per chunk
  2. Filter           → exclude documents with zero relevant chunks
  3. Rank             → sort surviving documents by their single best relevant chunk score
  4. Top-5            → return top-5 documents in full (all chunks in reading order)
"""
from __future__ import annotations

import logging
from itertools import groupby
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


def _merge_chunks_deoverlap(chunks: List[str], max_overlap: int = 300) -> str:
    """
    Merges an ordered list of chunks into a single string, removing the
    repeated overlap region that chunk_text() carries forward between chunks.

    chunk_text() seeds each new chunk with the last `overlap` characters of
    the previous chunk (snapped to a sentence/word boundary). This helper
    detects that repeated prefix by scanning the tail of the accumulated
    result for a match against the head of the next chunk, up to
    `max_overlap` characters, and strips it before appending.

    Chunks with no detectable overlap (e.g. historical chunks ingested before
    overlap was introduced) are simply concatenated with a newline.
    """
    if not chunks:
        return ""

    result = chunks[0]
    for next_chunk in chunks[1:]:
        # Search window: look at slightly more than max_overlap to be safe
        search_window = min(len(result), max_overlap + 50)
        tail = result[-search_window:]
        head = next_chunk[:search_window]

        # Find the longest suffix of `tail` that is a prefix of `next_chunk`
        overlap_len = 0
        # Start from the largest possible match and work down
        for length in range(min(len(tail), len(head)), 10, -1):
            if tail.endswith(head[:length]):
                overlap_len = length
                break

        result += "\n" + next_chunk[overlap_len:].lstrip()

    return result


async def rerank_and_group_documents(
    chunks: List[Dict],
    goal_str: str,
    reranker,
    top_k_docs: int = 5,
) -> Tuple[List[str], List[str]]:
    """
    Selects the top_k_docs most relevant documents from the candidate pool.

    A document is eligible only if at least one of its chunks is marked
    is_relevant=True. Eligible documents are ranked by their single highest
    relevant chunk score (descending). Each winning document is returned in
    full with all chunks in original reading order (chunk_index).

    Returns ([], []) if no documents have any relevant chunks (caller returns MISS).
    """
    if not chunks:
        return [], []

    # 1. Score all chunks in one LLM call
    chunk_texts = [c["text"] for c in chunks]
    assessments = await reranker.assess_chunks(chunk_texts, goal_str)

    # 2. Group chunks by document fingerprint
    chunks_sorted = sorted(chunks, key=lambda c: c["metadata"]["document_fingerprint"])
    doc_groups: Dict[str, List[Dict]] = {}
    for fingerprint, group in groupby(
        chunks_sorted, key=lambda c: c["metadata"]["document_fingerprint"]
    ):
        doc_groups[fingerprint] = list(group)

    # 3. Map each flat chunk index to its fingerprint
    chunk_to_fingerprint = {
        i: chunks[i]["metadata"]["document_fingerprint"]
        for i in range(len(chunks))
    }

    # 4. Compute per-document best relevant chunk score
    doc_best_score: Dict[str, float] = {}
    doc_has_relevant: Dict[str, bool] = {}

    for i, assessment in enumerate(assessments):
        fp = chunk_to_fingerprint[i]
        if assessment.is_relevant:
            doc_has_relevant[fp] = True
            if assessment.score > doc_best_score.get(fp, -1.0):
                doc_best_score[fp] = assessment.score
            logger.debug(
                "CacheGate: relevant chunk (score=%.1f) from %s — Reason: %s",
                assessment.score,
                chunks[i]["metadata"].get("source_url", fp),
                assessment.reasoning,
            )
        else:
            logger.debug(
                "CacheGate: irrelevant chunk from %s — Reason: %s",
                chunks[i]["metadata"].get("source_url", fp),
                assessment.reasoning,
            )
            if fp not in doc_has_relevant:
                doc_has_relevant[fp] = False

    # 5. Filter: only documents with at least one relevant chunk survive
    eligible = [fp for fp, has_rel in doc_has_relevant.items() if has_rel]
    if not eligible:
        return [], []  # caller converts to MISS

    # 6. Rank by best relevant chunk score (descending), take top-5
    top_fingerprints = sorted(
        eligible,
        key=lambda f: doc_best_score.get(f, 0.0),
        reverse=True,
    )[:top_k_docs]

    # 7. Assemble each winning document with ALL chunks in reading order,
    #    stripping the ~200-char overlap that chunk_text() carries forward
    #    between consecutive chunks to avoid duplicated text.
    formatted_blocks: List[str] = []
    sources: List[str] = []
    for fingerprint in top_fingerprints:
        group_sorted = sorted(
            doc_groups[fingerprint],
            key=lambda c: c["metadata"].get("chunk_index", 0),
        )
        source = group_sorted[0]["metadata"].get("source_url", fingerprint)
        sources.append(source)
        text = _merge_chunks_deoverlap([c["text"] for c in group_sorted])
        formatted_blocks.append(f"--- Document: {source} ---\n{text}")

    logger.info(
        "CacheGate: returning %d/%d eligible documents for goal='%s...'",
        len(formatted_blocks),
        len(eligible),
        goal_str[:60],
    )
    return formatted_blocks, sources

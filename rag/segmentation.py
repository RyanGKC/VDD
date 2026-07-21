import math
from collections import Counter
from typing import List, Optional

import spacy

import sys

try:
    _nlp = spacy.load("en_core_web_sm")
except OSError:
    import subprocess
    subprocess.run([sys.executable, "-m", "spacy", "download", "en_core_web_sm"])
    _nlp = spacy.load("en_core_web_sm")


def get_dominant_entity(text: str) -> Optional[str]:
    """
    Returns the most frequently mentioned ORG or PERSON entity in the
    given text, or None if no such entity is found.
    """
    doc = _nlp(text)
    entity_mentions = [ent.text for ent in doc.ents if ent.label_ in ("ORG", "PERSON")]
    if not entity_mentions:
        return None
    return Counter(entity_mentions).most_common(1)[0][0]

def _cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

def segment_chunks(
    chunks: List[str],
    embeddings: List[List[float]],
    similarity_threshold: float = 0.75,
    max_segment_size: int = 12,
) -> List[List[int]]:
    """
    Groups chunk indices into topic-coherent segments. A new segment
    starts when cosine similarity between consecutive chunks drops
    below similarity_threshold, OR when the dominant entity changes
    between consecutive chunks (even if similarity stays high).
    """
    if not embeddings:
        return []

    dominant_entities = [get_dominant_entity(c) for c in chunks]
    segments: List[List[int]] = [[0]]

    for i in range(1, len(embeddings)):
        current_segment = segments[-1]
        sim = _cosine_similarity(embeddings[i - 1], embeddings[i])

        entity_changed = (
            dominant_entities[i] is not None
            and dominant_entities[i - 1] is not None
            and dominant_entities[i] != dominant_entities[i - 1]
        )

        starts_new_segment = (
            sim < similarity_threshold
            or entity_changed
            or len(current_segment) >= max_segment_size
        )

        if starts_new_segment:
            segments.append([i])
        else:
            current_segment.append(i)

    return segments

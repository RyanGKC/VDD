from typing import List

import torch
from sentence_transformers import CrossEncoder

device = "cpu"
if torch.backends.mps.is_available():
    device = "mps"
elif torch.cuda.is_available():
    device = "cuda"

_cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", device=device)


def score_with_cross_encoder(goal_str: str, chunks: List[str]) -> List[float]:
    """
    Scores each chunk's relevance to the goal using a local cross-encoder
    model. Raw logits are passed through a sigmoid to get a bounded 0-1
    relevance signal per chunk, independent of any other chunk in the
    batch, then scaled to 0-10. Unlike batch min-max normalization, this
    doesn't force the best chunk in an arbitrary batch to read as a
    perfect match — a batch of entirely irrelevant chunks will correctly
    score low across the board instead of being stretched to fill 0-10.
    """
    if not chunks:
        return []
    pairs = [(goal_str, chunk) for chunk in chunks]
    raw_scores = _cross_encoder.predict(pairs, activation_fct=torch.nn.Sigmoid())
    return [float(s) * 10.0 for s in raw_scores]

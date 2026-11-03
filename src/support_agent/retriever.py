"""Load the prebuilt FAISS index once and expose category-aware retrieval."""
import json
from pathlib import Path

import faiss
import numpy as np
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings

load_dotenv()
INDEX_DIR = Path(__file__).resolve().parents[2] / "index"

_meta = json.loads((INDEX_DIR / "meta.json").read_text())
_index = faiss.read_index(str(INDEX_DIR / "kb.faiss"))
_emb = OpenAIEmbeddings(model=_meta["embedding_model"])
_chunks = _meta["chunks"]

MIN_SCORE = 0.30  # cosine similarity; tune with evals
FETCH_K = 20


def _search(query: str, k: int, categories: set[str] | None):
    q = np.array([_emb.embed_query(query)], dtype="float32")
    faiss.normalize_L2(q)
    scores, ids = _index.search(q, min(FETCH_K if categories else k, _index.ntotal))
    out = []
    for s, i in zip(scores[0], ids[0]):
        if i < 0:
            continue
        c = _chunks[i]
        if categories is None or c["category"] in categories:
            out.append((float(s), c))
        if len(out) == k:
            break
    return out


def retrieve(query: str, category: str, k: int = 4) -> list[dict]:
    """Filtered search (category + general); fall back to unfiltered if weak."""
    hits = _search(query, k, {category, "general"})
    if not hits or hits[0][0] < MIN_SCORE:
        hits = _search(query, k, None)
    return [c | {"score": s} for s, c in hits if s >= MIN_SCORE]

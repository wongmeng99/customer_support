"""Build the FAISS index from kb/*.md. Run: uv run python scripts/build_index.py"""
import json
import re
from pathlib import Path

import faiss
import numpy as np
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings

load_dotenv()
ROOT = Path(__file__).resolve().parents[1]
MODEL = "text-embedding-3-small"

chunks = []
for f in sorted((ROOT / "kb").glob("*.md")):
    # one chunk per "# Heading" section (KB articles are short)
    for sec in re.split(r"^# ", f.read_text(), flags=re.M):
        if sec.strip():
            title, _, body = sec.partition("\n")
            chunks.append({"category": f.stem, "source": f.name, "title": title.strip(),
                           "text": f"{title.strip()}\n{body.strip()}"})

vecs = np.array(OpenAIEmbeddings(model=MODEL).embed_documents([c["text"] for c in chunks]), dtype="float32")
faiss.normalize_L2(vecs)
index = faiss.IndexFlatIP(vecs.shape[1])  # inner product on unit vectors = cosine
index.add(vecs)

out = ROOT / "index"
out.mkdir(exist_ok=True)
faiss.write_index(index, str(out / "kb.faiss"))
(out / "meta.json").write_text(json.dumps({"embedding_model": MODEL, "chunks": chunks}, indent=2))
print(f"Indexed {len(chunks)} chunks -> {out}")

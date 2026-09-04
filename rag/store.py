"""
Hybrid retrieval over the AIRA corpus.

    py -3.11 rag/store.py --rebuild
    py -3.11 rag/store.py --ask "how long should a cough last"

WHY HYBRID, AND NOT JUST EMBEDDINGS

Dense retrieval is good at "my stomach burns after eating" -> dyspepsia, which
keyword search cannot do. It is bad at exact tokens: ask about "CBNAAT" or
"PM-JAY" or "NG12 1.2.1" and a 384-dimensional sentence embedding will happily
return something adjacent and wrong. Those tokens are precisely the ones a
clinician types. BM25 nails them and cannot generalise at all.

So both, fused on normalised scores. 0.65 dense / 0.35 lexical, set by hand
after watching which half fixed which failure - dense carries the paraphrases,
lexical carries the identifiers.

WHY A SCORE FLOOR

Every retrieval system returns k results, including for a question the corpus
knows nothing about. Ranking is relative; it does not tell you whether the top
hit is any good. So a passage below MIN_SCORE is dropped even if that leaves
nothing, because "I do not have a source for that" is a correct answer and the
nearest unrelated paragraph is not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag.corpus import Chunk, build  # noqa: E402

INDEX_DIR = Path("rag/index")
COLLECTION = "aira_corpus"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

DENSE_WEIGHT = 0.65
LEXICAL_WEIGHT = 0.35
MIN_SCORE = 0.28


@dataclass
class Hit:
    chunk: Chunk
    score: float
    dense: float
    lexical: float

    def cite(self) -> dict:
        return {
            "id": self.chunk.id,
            "source": self.chunk.source,
            "section": self.chunk.section,
            "quote": self.chunk.text,
            "kind": self.chunk.kind,
            "score": round(self.score, 4),
        }


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _minmax(xs: list[float]) -> list[float]:
    if not xs:
        return []
    lo, hi = min(xs), max(xs)
    if hi - lo < 1e-9:
        return [1.0 if hi > 0 else 0.0] * len(xs)
    return [(x - lo) / (hi - lo) for x in xs]


class Retriever:
    """Loads the corpus once, indexes it once, answers many queries.

    Falls back cleanly: if chromadb or sentence-transformers are missing the
    dense half is skipped and BM25 alone answers. A degraded retriever that
    still cites correctly is far better than an import error at the counter.
    """

    def __init__(self) -> None:
        self.chunks: list[Chunk] = build()
        self.by_id = {c.id: c for c in self.chunks}
        self.fingerprint = hashlib.sha1(
            "".join(sorted(c.id + c.text for c in self.chunks)).encode()
        ).hexdigest()[:16]

        self._bm25 = None
        self._collection = None
        self._embedder = None
        self.backend = "lexical-only"

        self._build_lexical()
        self._build_dense()

    # ── lexical ──────────────────────────────────────────────────────────
    def _build_lexical(self) -> None:
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            return
        self._corpus_tokens = [_tokens(c.text) for c in self.chunks]
        self._bm25 = BM25Okapi(self._corpus_tokens)

    # ── dense ────────────────────────────────────────────────────────────
    def _build_dense(self) -> None:
        try:
            import chromadb
            from sentence_transformers import SentenceTransformer
        except ImportError:
            return

        try:
            self._embedder = SentenceTransformer(EMBED_MODEL)
            INDEX_DIR.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(INDEX_DIR))
            self._collection = client.get_or_create_collection(
                COLLECTION, metadata={"hnsw:space": "cosine"}
            )

            stamp = INDEX_DIR / "fingerprint.txt"
            current = stamp.read_text().strip() if stamp.exists() else ""
            if current != self.fingerprint or self._collection.count() != len(self.chunks):
                self._reindex(client)
                stamp.write_text(self.fingerprint)

            self.backend = "hybrid" if self._bm25 else "dense-only"
        except Exception as exc:  # pragma: no cover - environment dependent
            print(f"[rag] dense retrieval unavailable ({exc}); using BM25 only")
            self._collection = None
            self._embedder = None

    def _reindex(self, client) -> None:
        client.delete_collection(COLLECTION)
        self._collection = client.get_or_create_collection(
            COLLECTION, metadata={"hnsw:space": "cosine"}
        )
        texts = [c.text for c in self.chunks]
        vectors = self._embedder.encode(texts, batch_size=64, show_progress_bar=False)
        self._collection.add(
            ids=[c.id for c in self.chunks],
            documents=texts,
            embeddings=[v.tolist() for v in vectors],
            metadatas=[
                {
                    "kind": c.kind,
                    "source": c.source,
                    "section": c.section or "",
                    "topic": c.topic,
                    "audience": c.audience,
                }
                for c in self.chunks
            ],
        )

    # ── search ───────────────────────────────────────────────────────────
    def search(
        self,
        query: str,
        k: int = 6,
        audience: str | None = None,
        pool: int = 30,
    ) -> list[Hit]:
        dense: dict[str, float] = {}
        if self._collection is not None and self._embedder is not None:
            vec = self._embedder.encode([query])[0].tolist()
            res = self._collection.query(query_embeddings=[vec], n_results=min(pool, len(self.chunks)))
            ids = res["ids"][0]
            # Chroma returns cosine DISTANCE; similarity is 1 - distance.
            sims = [1.0 - d for d in res["distances"][0]]
            for cid, sim in zip(ids, _minmax(sims)):
                dense[cid] = sim

        lexical: dict[str, float] = {}
        if self._bm25 is not None:
            scores = self._bm25.get_scores(_tokens(query))
            order = sorted(range(len(scores)), key=lambda i: -scores[i])[:pool]
            raw = [float(scores[i]) for i in order]
            for i, norm in zip(order, _minmax(raw)):
                lexical[self.chunks[i].id] = norm

        fused: list[Hit] = []
        for cid in set(dense) | set(lexical):
            d, l = dense.get(cid, 0.0), lexical.get(cid, 0.0)
            chunk = self.by_id[cid]
            if audience and chunk.audience not in ("both", audience):
                continue
            fused.append(
                Hit(chunk=chunk, score=DENSE_WEIGHT * d + LEXICAL_WEIGHT * l, dense=d, lexical=l)
            )

        fused.sort(key=lambda h: -h.score)
        kept = [h for h in fused if h.score >= MIN_SCORE][:k]
        return kept

    def stats(self) -> dict:
        return {
            "backend": self.backend,
            "chunks": len(self.chunks),
            "quotes": sum(1 for c in self.chunks if c.kind == "quote"),
            "summaries": sum(1 for c in self.chunks if c.kind == "summary"),
            "embedding_model": EMBED_MODEL if self._embedder else None,
            "fingerprint": self.fingerprint,
            "weights": {"dense": DENSE_WEIGHT, "lexical": LEXICAL_WEIGHT},
            "min_score": MIN_SCORE,
        }


@lru_cache(maxsize=1)
def retriever() -> Retriever:
    return Retriever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--ask", default=None)
    ap.add_argument("--audience", default=None)
    args = ap.parse_args()

    if args.rebuild and (INDEX_DIR / "fingerprint.txt").exists():
        (INDEX_DIR / "fingerprint.txt").unlink()

    r = retriever()
    print(json.dumps(r.stats(), indent=2))

    if args.ask:
        print(f"\nQ: {args.ask}\n")
        for h in r.search(args.ask, audience=args.audience):
            print(f"  [{h.score:.3f}] ({h.chunk.kind}) {h.chunk.source} {h.chunk.section or ''}")
            print(f"      {h.chunk.text[:190]}...")

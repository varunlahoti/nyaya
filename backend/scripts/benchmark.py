"""Retrieval benchmark — prove the hybrid upgrade actually helps.

Runs a labeled query set (eval/queries.jsonl: facts -> expected judgment ids)
through each retrieval mode over the in-memory corpus and reports recall@k and
MRR. This isolates *retrieval* quality (candidate generation) — the thing the
hybrid upgrade changes — from the LLM rerank, so it runs fully offline with no
API keys.

Modes compared:
    bm25          lexical only
    vector        semantic only
    hybrid-rrf    both, fused by Reciprocal Rank Fusion   (the new default)
    hybrid-weight both, fused by score-normalisation blend (the old method)

    python -m scripts.benchmark
    python -m scripts.benchmark --k 5 --embeddings voyage   # with a real key

NOTE: with EMBEDDINGS_PROVIDER=hash (dev fallback) the vector numbers are a
floor, not the real semantic ceiling. Re-run with voyage/openai to measure the
true vector + hybrid quality — that is the embedding de-risk step.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]


def _load_queries() -> List[dict]:
    path = ROOT / "eval" / "queries.jsonl"
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


async def _corpus():
    import json as _json

    from app.config import settings
    from app.services import ingest
    from app.services.memory_store import InMemoryCorpus

    records: Dict[str, dict] = {}
    seed = ROOT / settings.SEED_CORPUS_PATH
    if seed.exists():
        for r in _json.loads(seed.read_text(encoding="utf-8")):
            records[r["id"]] = r
    for r in ingest.load_jsonl():
        records[r["id"]] = r
    corpus = InMemoryCorpus()
    await corpus.load(list(records.values()))
    return corpus


def _ids(candidates) -> List[str]:
    """Ranked judgment ids from a candidate list (dedupe, keep order)."""
    out, seen = [], set()
    for c in candidates:
        jid = c.source_doc_id
        if jid not in seen:
            seen.add(jid)
            out.append(jid)
    return out


async def _ranked(mode: str, corpus, facts: str, limit: int) -> List[str]:
    from app.schemas import RetrievalQuery
    from app.services.pipeline import SearchPipeline
    from app.services.retrievers.bm25 import BM25Retriever
    from app.services.retrievers.vector import VectorRetriever

    q = RetrievalQuery(text=facts, boolean=facts, limit=limit)
    vec = VectorRetriever(db=corpus)
    bm = BM25Retriever(db=corpus)

    if mode == "bm25":
        return _ids(await bm.search(q))
    if mode == "vector":
        return _ids(await vec.search(q))

    lists = [await vec.search(q), await bm.search(q)]
    pipe = SearchPipeline(db=corpus)
    if mode == "hybrid-weight":
        fused = pipe._merge_and_dedupe([c for lst in lists for c in lst])
    else:
        fused = pipe._fuse_rrf(lists)
    return _ids(fused)


def _metrics(rankings: List[List[str]], expected: List[List[str]], k: int) -> dict:
    n = len(rankings)
    hits_at = {1: 0, 5: 0, k: 0}
    rr_sum = 0.0
    for ranked, exp in zip(rankings, expected):
        exp_set = set(exp)
        rank = next((i + 1 for i, jid in enumerate(ranked) if jid in exp_set), None)
        if rank:
            rr_sum += 1.0 / rank
            for kk in hits_at:
                if rank <= kk:
                    hits_at[kk] += 1
    return {
        "recall@1": hits_at[1] / n,
        "recall@5": hits_at[5] / n,
        f"recall@{k}": hits_at[k] / n,
        "mrr": rr_sum / n,
    }


async def main(k: int) -> None:
    queries = _load_queries()
    corpus = await _corpus()
    expected = [q["expected"] for q in queries]

    modes = ["bm25", "vector", "hybrid-weight", "hybrid-rrf"]
    print(f"\nRetrieval benchmark — {len(queries)} labeled queries, k={k}, "
          f"embeddings={os.getenv('EMBEDDINGS_PROVIDER', 'hash')}\n")
    print(f"{'mode':<14} {'recall@1':>9} {'recall@5':>9} {'recall@'+str(k):>10} {'MRR':>7}")
    print("-" * 54)
    for mode in modes:
        rankings = [await _ranked(mode, corpus, q["facts"], k) for q in queries]
        m = _metrics(rankings, expected, k)
        print(f"{mode:<14} {m['recall@1']:>9.2f} {m['recall@5']:>9.2f} "
              f"{m['recall@'+str(k)]:>10.2f} {m['mrr']:>7.3f}")
    print()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10, help="cutoff for recall@k")
    ap.add_argument("--embeddings", help="override EMBEDDINGS_PROVIDER for the run")
    args = ap.parse_args()
    if args.embeddings:
        os.environ["EMBEDDINGS_PROVIDER"] = args.embeddings
    asyncio.run(main(args.k))

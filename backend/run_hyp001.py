"""Run HYP-001 golden-set evaluation (T8: learned ColBERT + real BGE rerank)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .rag.eval import run_hyp001_matrix


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    default_repo = root / "tests" / "fixtures" / "golden_repo"
    default_queries = root / "tests" / "fixtures" / "hyp001_golden_queries.json"
    default_output = root / "docs" / "hyp001_results_learned.json"

    parser = argparse.ArgumentParser(description="HYP-001 recall@k ablation matrix")
    parser.add_argument("--repo", type=Path, default=default_repo, help="Repo root to index")
    parser.add_argument("--queries", type=Path, default=default_queries, help="Golden queries JSON")
    parser.add_argument("-k", type=int, default=10, help="Recall@k cutoff")
    parser.add_argument(
        "--colbert",
        choices=("hash", "learned"),
        default="learned",
        help="ColBERT index mode for variants D/E",
    )
    parser.add_argument(
        "--rerank",
        choices=("mock", "bge"),
        default="bge",
        help="Reranker: mock (flat 0.5) or bge (sentence-transformers)",
    )
    parser.add_argument(
        "--colbert-dir",
        type=Path,
        default=None,
        help="Override ColBERT index directory",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=default_output,
        help="Write JSON results here",
    )
    args = parser.parse_args(argv)

    if not args.repo.is_dir():
        print(f"Repo not found: {args.repo}", file=sys.stderr)
        return 1
    if not args.queries.is_file():
        print(f"Queries not found: {args.queries}", file=sys.stderr)
        return 1

    print(
        f"HYP-001: repo={args.repo.name} colbert={args.colbert} rerank={args.rerank} k={args.k}",
        flush=True,
    )
    matrix = run_hyp001_matrix(
        args.repo,
        args.queries,
        k=args.k,
        colbert_mode=args.colbert,
        rerank_mode=args.rerank,
        colbert_index_dir=args.colbert_dir,
    )
    matrix["run_at"] = datetime.now(timezone.utc).isoformat()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(matrix, indent=2), encoding="utf-8")

    print("\nrecall@{} by checkpoint:".format(args.k))
    for checkpoint, scores in matrix["summary_by_checkpoint"].items():
        print(f"  [{checkpoint}]")
        for variant, score in scores.items():
            print(f"    {variant}: {score:.3f}")
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
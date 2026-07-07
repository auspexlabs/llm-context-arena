"""Run HYP-002: router × reranker matrix on variant F (DEC-010 stack)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .rag.eval_hyp002 import HYP002_RERANKERS, HYP002_ROUTERS, run_hyp002_matrix


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    default_golden_repo = root / "tests" / "fixtures" / "golden_repo"
    default_arena_repo = root / "backend"
    default_golden_queries = root / "tests" / "fixtures" / "hyp001_golden_queries.json"
    default_probes = root / "tests" / "fixtures" / "hyp002_architectural_probes.json"
    default_output = root / "docs" / "hyp002_results.json"

    parser = argparse.ArgumentParser(description="HYP-002 router × reranker on variant F")
    parser.add_argument("--golden-repo", type=Path, default=default_golden_repo)
    parser.add_argument("--arena-repo", type=Path, default=default_arena_repo)
    parser.add_argument("--queries", type=Path, default=default_golden_queries)
    parser.add_argument("--probes", type=Path, default=default_probes)
    parser.add_argument("-k", type=int, default=10)
    parser.add_argument(
        "--colbert",
        choices=("hash", "learned"),
        default="learned",
    )
    parser.add_argument(
        "--routers",
        default=",".join(HYP002_ROUTERS),
        help="Comma-separated: regex, embedding",
    )
    parser.add_argument(
        "--rerankers",
        default="mock,bge",
        help="Comma-separated: mock, bge, jina",
    )
    parser.add_argument("--colbert-dir", type=Path, default=None)
    parser.add_argument(
        "--reuse-colbert",
        action="store_true",
        help="Skip ColBERT re-encode when index dirs already exist",
    )
    parser.add_argument("--output", type=Path, default=default_output)
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge cell results into existing --output instead of replacing",
    )
    args = parser.parse_args(argv)

    for label, path in (
        ("golden repo", args.golden_repo),
        ("arena repo", args.arena_repo),
        ("queries", args.queries),
        ("probes", args.probes),
    ):
        if not path.exists():
            print(f"{label} not found: {path}", file=sys.stderr)
            return 1

    routers = tuple(r.strip() for r in args.routers.split(",") if r.strip())
    rerankers = tuple(r.strip() for r in args.rerankers.split(",") if r.strip())

    print(
        f"HYP-002: variant=F colbert={args.colbert} routers={routers} rerankers={rerankers} k={args.k}",
        flush=True,
    )
    matrix = run_hyp002_matrix(
        args.golden_repo,
        args.queries,
        args.arena_repo,
        args.probes,
        k=args.k,
        colbert_mode=args.colbert,
        colbert_index_dir=args.colbert_dir,
        rebuild_colbert=not args.reuse_colbert,
        routers=routers,
        rerankers=rerankers,
    )
    matrix["run_at"] = datetime.now(timezone.utc).isoformat()

    if args.merge and args.output.is_file():
        prior = json.loads(args.output.read_text(encoding="utf-8"))
        prior.setdefault("cells", {}).update(matrix["cells"])
        for section in ("golden_recall", "architectural_purity", "router_accuracy"):
            prior.setdefault("summary", {}).setdefault(section, {}).update(
                matrix["summary"][section]
            )
        prior["run_at"] = matrix["run_at"]
        prior["jina_rerun_at"] = matrix["run_at"]
        matrix = prior

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(matrix, indent=2), encoding="utf-8")

    print("\nGolden recall@{}:".format(args.k))
    for key, score in matrix["summary"]["golden_recall"].items():
        print(f"  {key}: {score:.3f}")

    print("\nArchitectural answer-slot purity:")
    for key, score in matrix["summary"]["architectural_purity"].items():
        print(f"  {key}: {score:.3f}")

    print("\nRouter classification accuracy (golden categories):")
    for key, score in matrix["summary"]["router_accuracy"].items():
        print(f"  {key}: {score:.3f}")

    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
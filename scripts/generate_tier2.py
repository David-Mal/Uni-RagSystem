"""Deterministic, partition-enforced development export; final evaluation fails closed."""

import argparse
from pathlib import Path
import sys
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from src.datagen.partition import load_partition  # noqa: E402
from src.exercises.loader import exercise_ids  # noqa: E402
from src.sim.config import load_development_config  # noqa: E402
from src.sim.integration import PENDING_EVALUATION_DECISIONS, prepare_development_export  # noqa: E402


def main(argv: Sequence[str] | None = None, *, repository_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Development-only OpenGym simulator; golden generation remains blocked.")
    parser.add_argument("--development", action="store_true", help="explicitly select non-evaluation generation")
    parser.add_argument("--n", type=int, default=150, help="positive development scenario count")
    parser.add_argument("--seed", type=int, help="first actual development-pool seed")
    parser.add_argument("--config", type=Path, help="explicit note-free development JSON configuration")
    parser.add_argument("--partition", type=Path, help="P1 manifest path; default is the shared project manifest")
    parser.add_argument("--out", type=Path, required=True, help="new development directory; golden/pilot paths rejected")
    args = parser.parse_args(argv)
    if args.n < 1:
        parser.error("--n must be positive")
    if not args.development:
        print("Final evaluation generation is blocked. No output was created.", file=sys.stderr)
        for blocker in PENDING_EVALUATION_DECISIONS:
            print(f"- {blocker}", file=sys.stderr)
        return 2
    if args.config is None or args.seed is None:
        parser.error("--development requires --config and --seed")
    root = REPOSITORY_ROOT if repository_root is None else repository_root
    try:
        if any(part.lower() in ("golden", "pilot") for part in args.out.resolve().parts):
            raise ValueError("development output cannot target a golden or pilot directory")
        if args.out.exists():
            raise ValueError("output directory already exists; no existing files will be overwritten")
        if args.partition and any(part.lower() in ("golden", "pilot") for part in args.partition.resolve().parts):
            raise ValueError("development manifest cannot be read from a golden or pilot directory")
        config = load_development_config(args.config)
        partition = load_partition(args.partition or root / "data/manifests/partition.yaml")
        exported = prepare_development_export(
            config.families, config.metadata, partition, config.template_bindings,
            n=args.n, seed=args.seed, known_exercise_ids=exercise_ids(), persona_ids=config.persona_ids,
        )
        exported.write(args.out)
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        print(f"Development generation failed: {exc}", file=sys.stderr)
        return 2
    print(f"Created {args.n} DEVELOPMENT scenarios, {exported.summary['sessions']} sessions, "
          f"{exported.summary['set_rows']} set rows. Partition validation passed.")
    print("No validated evaluation ground truth. This export does not run ingestion; final annotations remain pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

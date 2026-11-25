"""Human-operated entry point; no evaluation output until Fi2 integration exists."""

import argparse
from pathlib import Path
import sys
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from src.sim.quotas import QuotaRequirements  # noqa: E402


def missing_dependencies(root: Path) -> tuple[str, ...]:
    """Check explicit interface paths only, without opening evaluation content."""
    required = (
        ("D2 export contract", "docs/opengym-export-format.md"),
        ("D3 indicator contract", "docs/indicator-spec.md"),
        ("P1 manifest", "data/manifests/partition.yaml"),
        ("P1 loader", "src/datagen/partition.py"),
        ("D5 OpenGym adapter", "src/ingest/adapters/opengym.py"),
    )
    return tuple(f"{name}: {path}" for name, path in required if not (root / path).is_file())


def main(argv: Sequence[str] | None = None, *, repository_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Tier 2 generator interface. Generation is blocked pending the written contracts and integration."
    )
    parser.add_argument("--n", type=int, default=150, help="scenario count (at least 150)")
    parser.add_argument("--out", type=Path, required=True, help="future output directory; currently never opened or created")
    args = parser.parse_args(argv)
    if args.n < QuotaRequirements().total:
        parser.error("--n must be at least 150 for the full Tier 2 quotas")
    root = REPOSITORY_ROOT if repository_root is None else repository_root
    blockers = list(missing_dependencies(root))
    blockers.append(
        "The simulator core works, but evaluation generation still requires actual D2/D3/P1/D5 integration and approved held-out templates."
    )
    print("Tier 2 generation is blocked. No output was created.", file=sys.stderr)
    for blocker in blockers:
        print(f"- {blocker}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

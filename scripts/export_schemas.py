"""Export the JSON Schemas of the shared models to ``schemas/*.json``.

Usage (from the repo root)::

    uv run python scripts/export_schemas.py            # write schemas/
    uv run python scripts/export_schemas.py --check    # exit 1 if schemas/ is stale
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    """Write the schemas, or with ``--check`` report stale files without writing."""
    from src.schemas.json_schema import EXPORTED_MODELS, export_schemas, render_schema

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "schemas")
    parser.add_argument("--check", action="store_true", help="fail if committed schemas differ")
    args = parser.parse_args(argv)

    if args.check:
        stale = [
            stem
            for stem, model in EXPORTED_MODELS.items()
            if not (args.out / f"{stem}.json").is_file()
            or (args.out / f"{stem}.json").read_text(encoding="utf-8") != render_schema(model)
        ]
        if stale:
            print(f"stale schemas: {stale}; run scripts/export_schemas.py", file=sys.stderr)
            return 1
        print("schemas up to date")
        return 0

    for path in export_schemas(args.out):
        print(f"wrote {path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Contributing

## Pull requests

- Work on a branch (`feat/<issue id>-<topic>`, `data/...`, `docs/...`) and open a PR against `main`.
- Every PR links its issue in the description: `Closes #n` (or `Refs #n` if it does not finish the issue).
- At least **one reviewer** who is not the author reviews the PR.
- CI must be green: `uv run ruff check` and `uv run pytest`.
- Small, reviewable commits. At least one meaningful commit per member per week (plan §8.1).

## Weekly status note

One file per ISO week in `docs/status/YYYY-WNN.md`, copied from [docs/status/TEMPLATE.md](docs/status/TEMPLATE.md).

## Rules that protect the results

- Tools are deterministic: no randomness, no network, no model calls. Tests use no network.
- Thresholds live in `configs/`, not in code.
- Do not guess export formats, thresholds or citations. Mark unverified facts `[TO VERIFY]`.
- Nobody except the golden authors opens `data/golden/` before the freeze. Golden text never goes into prompts.
- `src/reference/` is written from the specification only and never imports from `src/tools/`.

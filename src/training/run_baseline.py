"""Zero-shot / few-shot / zero-shot + constrained-decoding baselines on dev (issue F5, plan §6.1, §6.5, §7 E3).

    python -m src.training.run_baseline --model Qwen/Qwen3-1.7B --setup zero_shot \
        --data data/training/dev.jsonl --out results/E3/dev_qwen3-1.7b_zero_shot/

Greedy decoding. ``zero_shot_cd`` constrains the output with Outlines to ``extraction_json_schema(exercise_ids)``
(F2). Writes ``preds.jsonl`` in the harness format (one object per ``item_id``: ``pred`` = labels or null,
``raw``, ``error``), plus ``gold.jsonl`` (the dev labels, NOT golden), ``config.yaml`` and ``run_manifest.json``.
Field-level F1 comes from the evaluation harness (P2). This script reports only JSON validity and the failure rate.
Never run it on files under ``data/golden/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from src.schemas import extraction_json_schema
from src.training.extraction_io import build_prompt, default_exercise_ids, parse_output, pick_fewshot

SETUPS = ("zero_shot", "few_shot", "zero_shot_cd", "few_shot_cd")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    """Read JSONL items; refuses golden paths."""
    if "golden" in {p.lower() for p in path.resolve().parts}:
        raise ValueError("baselines run on dev only; refusing a golden file")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows[:limit] if limit else rows


def load_model(name: str, quant: str) -> tuple[Any, Any]:  # pragma: no cover - needs the ml group
    """Load tokenizer + causal LM. ``quant``: ``none`` (fp16 on GPU) or ``4bit`` (bitsandbytes NF4, for small GPUs)."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    tok = AutoTokenizer.from_pretrained(name)
    kwargs: dict[str, Any] = {"device_map": "auto"}
    if quant == "4bit":
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.float16,
        )
    else:
        kwargs["torch_dtype"] = torch.float16 if torch.cuda.is_available() else torch.float32
    model = AutoModelForCausalLM.from_pretrained(name, **kwargs)
    model.eval()
    return tok, model


def chat_prompt(tok: Any, prompt: str) -> str:
    """Wrap the prompt in the model's chat template; Qwen3 thinking is turned off."""
    messages = [{"role": "user", "content": prompt}]
    try:
        return tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    except TypeError:
        return tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


class Generator:  # pragma: no cover - needs the ml group
    """Greedy generation, free or JSON-schema constrained (Outlines 1.x API, falling back to 0.x)."""

    def __init__(self, tok: Any, model: Any, schema: dict[str, Any] | None, max_new_tokens: int) -> None:
        self.tok, self.model, self.max_new_tokens = tok, model, max_new_tokens
        self._constrained = None
        if schema is not None:
            import outlines

            schema_str = json.dumps(schema)
            if hasattr(outlines, "from_transformers"):  # outlines >= 1.0
                from outlines.types import JsonSchema

                om = outlines.from_transformers(model, tok)
                gen = outlines.Generator(om, JsonSchema(schema_str))
                self._constrained = lambda p: gen(p, max_new_tokens=max_new_tokens, do_sample=False)
            else:  # outlines 0.x
                om = outlines.models.Transformers(model, tok)
                gen = outlines.generate.json(om, schema_str, sampler=outlines.samplers.greedy())
                self._constrained = lambda p: json.dumps(gen(p, max_tokens=max_new_tokens))

    def __call__(self, prompt: str) -> str:
        import torch

        if self._constrained is not None:
            out = self._constrained(prompt)
            return out if isinstance(out, str) else json.dumps(out)
        enc = self.tok(prompt, return_tensors="pt").to(self.model.device)
        with torch.no_grad():
            ids = self.model.generate(
                **enc, max_new_tokens=self.max_new_tokens, do_sample=False, pad_token_id=self.tok.eos_token_id
            )
        return self.tok.decode(ids[0, enc["input_ids"].shape[1] :], skip_special_tokens=True)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - needs the ml group and a model download
    """Run one baseline setup and write predictions + run metadata."""
    parser = argparse.ArgumentParser(description="Extraction baselines on dev (E3).")
    parser.add_argument("--model", required=True)
    parser.add_argument("--setup", choices=SETUPS, required=True)
    parser.add_argument("--data", type=Path, default=Path("data/training/dev.jsonl"))
    parser.add_argument("--train", type=Path, default=Path("data/training/train.jsonl"), help="few-shot source")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, help="first N items only (smoke runs)")
    parser.add_argument("--quant", choices=("none", "4bit"), default="none")
    parser.add_argument("--max-new-tokens", type=int, default=160)
    args = parser.parse_args(argv)

    import torch
    import transformers

    items = read_jsonl(args.data, args.limit)
    ids = default_exercise_ids()
    shots = pick_fewshot(read_jsonl(args.train)) if args.setup.startswith("few_shot") else []
    tok, model = load_model(args.model, args.quant)
    schema = extraction_json_schema(ids) if args.setup.endswith("_cd") else None
    generate = Generator(tok, model, schema, args.max_new_tokens)

    args.out.mkdir(parents=True, exist_ok=True)
    errors: dict[str, int] = {}
    latencies: list[float] = []
    with (
        (args.out / "preds.jsonl").open("w", encoding="utf-8", newline="\n") as fp,
        (args.out / "gold.jsonl").open("w", encoding="utf-8", newline="\n") as fg,
    ):
        for it in items:
            prompt = chat_prompt(tok, build_prompt(it["text"], args.setup, ids, shots))
            t0 = time.perf_counter()
            raw = generate(prompt)
            latencies.append(time.perf_counter() - t0)
            pred, err = parse_output(raw, ids)
            if err:
                errors[err] = errors.get(err, 0) + 1
            fp.write(json.dumps({"item_id": it["item_id"], "pred": pred, "raw": raw, "error": err}) + "\n")
            fg.write(json.dumps({"item_id": it["item_id"], "labels": it["labels"]}) + "\n")

    n = len(items)
    metrics = {
        "n": n,
        "json_validity": (n - errors.get("no_json", 0) - errors.get("invalid_json", 0)) / n,
        "schema_validity": (n - sum(errors.values())) / n,
        "failure_rate": sum(errors.values()) / n,
        "errors": errors,
        "latency_s_mean": sum(latencies) / n,
        "latency_s_p95": sorted(latencies)[int(0.95 * (n - 1))],
    }
    (args.out / "metrics_partial.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (args.out / "config.yaml").write_text(
        yaml.safe_dump(vars(args) | {"data": str(args.data), "out": str(args.out), "train": str(args.train)}),
        encoding="utf-8",
    )
    manifest = {
        "git_commit": _git_commit(),
        "model": args.model,
        "setup": args.setup,
        "quant": args.quant,
        "decoding": "greedy",
        "data_sha256": _sha256(args.data),
        "few_shot_item_ids": [s["item_id"] for s in shots],
        "exercise_vocab_size": len(ids),
        "versions": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        },
        "max_memory_mb": round(torch.cuda.max_memory_allocated() / 2**20) if torch.cuda.is_available() else None,
    }
    (args.out / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

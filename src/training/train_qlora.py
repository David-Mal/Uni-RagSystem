"""QLoRA fine-tuning of the extraction SLM (issue F6, plan §6.3).

PEFT + TRL ``SFTTrainer``. The base model is loaded in 4-bit NF4 with double quantization, with LoRA on the attention
and MLP projections. Training format: chat-templated instruction (``prompts/extraction_v0_ft.txt``) -> the strict
JSON of ``ExtractionResult``. Loss is on the completion only. Writes the adapter, ``train_log.json``,
``loss_curve.png``/``.csv``, ``config.yaml`` and ``run_manifest.json`` (library versions, GPU, peak memory, time per
epoch) to ``<output_dir>/<run_id>/``.

    python -m src.training.train_qlora --config configs/qlora_smoke.yaml

Never train or tune on ``data/golden/``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import random
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from src.training.extraction_io import build_prompt, label_json


def ft_prompt(text: str) -> str:
    """The short fine-tuning instruction for one note (no exercise list: the model learns the vocabulary)."""
    return build_prompt(text, "ft", [])


def read_train(
    path: Path, n: int | None, seed: int = 0, *, allow_unaudited: bool = False
) -> list[dict[str, Any]]:
    """Seeded, class-balanced subset of ``n`` items (all items if ``n`` is ``None``), in shuffled order.

    The training file is sorted by class, so its first 500 items are all green. Refuses golden and non-train items, and
    data that has not been through the leakage audit (P4) unless ``allow_unaudited``.
    """
    if "golden" in {p.lower() for p in path.resolve().parts}:
        raise ValueError("refusing to train on golden data")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(r.get("pool") != "train" for r in rows):
        raise ValueError("training items must come from the train pool")
    if not allow_unaudited and any("unaudited" in r.get("data_version", "") for r in rows):
        raise ValueError("this data has not been through the leakage audit (P4); rebuild it as train_v1 first")
    rng = random.Random(seed)
    if n is not None and n < len(rows):
        by_level: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            by_level.setdefault(r["labels"]["triage_level"], []).append(r)
        levels = sorted(by_level)
        rows = []
        for i, level in enumerate(levels):
            share = n // len(levels) + (1 if i < n % len(levels) else 0)
            rows += rng.sample(by_level[level], min(share, len(by_level[level])))
    rng.shuffle(rows)
    return rows


def to_examples(rows: list[dict[str, Any]], chat: Any, eos: str) -> list[dict[str, str]]:
    """Prompt/completion pairs. ``chat`` wraps a user message in the model's chat template."""
    return [{"prompt": chat(ft_prompt(r["text"])), "completion": label_json(r["labels"]) + eos} for r in rows]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()  # same on every OS


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - needs the ml group, a GPU and a model download
    """Train the QLoRA adapter and write the run directory."""
    parser = argparse.ArgumentParser(description="QLoRA fine-tuning of the extractor (F6).")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--train-file", help="override train_file")
    parser.add_argument("--output-dir", help="override output_dir")
    parser.add_argument("--allow-unaudited", action="store_true", help="pipeline check on data before the leakage audit")
    args = parser.parse_args(argv)

    import bitsandbytes
    import datasets
    import peft
    import torch
    import transformers
    import trl
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    from src.training.run_baseline import chat_prompt, compute_dtype

    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    for key in ("train_file", "output_dir"):
        if getattr(args, key):
            cfg[key] = getattr(args, key)
    transformers.set_seed(cfg["seed"])
    run_id = time.strftime("%Y%m%d-%H%M%S")
    out = Path(cfg["output_dir"]) / run_id
    out.mkdir(parents=True, exist_ok=True)

    q = cfg["quantization"]
    cdtype = compute_dtype() if q["compute_dtype"] == "auto" else getattr(torch, q["compute_dtype"])
    tok = AutoTokenizer.from_pretrained(cfg["base_model"])
    model = AutoModelForCausalLM.from_pretrained(
        cfg["base_model"],
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=q["load_in_4bit"],
            bnb_4bit_quant_type=q["quant_type"],
            bnb_4bit_use_double_quant=q["double_quant"],
            bnb_4bit_compute_dtype=cdtype,
        ),
        torch_dtype=cdtype,
        device_map="auto",
    )
    rows = read_train(
        Path(cfg["train_file"]), cfg.get("n_train"), cfg["seed"], allow_unaudited=args.allow_unaudited
    )
    ds = datasets.Dataset.from_list(to_examples(rows, lambda p: chat_prompt(tok, p), tok.eos_token))

    half = cdtype == torch.float16
    sft = SFTConfig(
        output_dir=str(out / "checkpoints"),
        num_train_epochs=cfg["epochs"],
        per_device_train_batch_size=cfg["batch_size"],
        gradient_accumulation_steps=cfg["grad_accum"],
        learning_rate=float(cfg["learning_rate"]),
        lr_scheduler_type=cfg["lr_scheduler"],
        warmup_ratio=cfg["warmup_ratio"],
        logging_steps=cfg["logging_steps"],
        max_length=cfg["max_length"],
        gradient_checkpointing=cfg["gradient_checkpointing"],
        fp16=half,
        bf16=cdtype == torch.bfloat16,
        save_strategy="no",
        report_to=[],
        seed=cfg["seed"],
    )
    lora = LoraConfig(
        r=cfg["lora"]["r"],
        lora_alpha=cfg["lora"]["alpha"],
        lora_dropout=cfg["lora"]["dropout"],
        target_modules=cfg["lora"]["target_modules"],
        task_type="CAUSAL_LM",
    )
    trainer = SFTTrainer(model=model, args=sft, train_dataset=ds, processing_class=tok, peft_config=lora)
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    result = trainer.train()
    seconds = time.time() - t0
    trainer.model.save_pretrained(out / "adapter")
    tok.save_pretrained(out / "adapter")

    log = [e for e in trainer.state.log_history if "loss" in e]
    (out / "train_log.json").write_text(json.dumps(trainer.state.log_history, indent=2), encoding="utf-8")
    with (out / "loss_curve.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["step", "epoch", "loss"])
        w.writerows([e["step"], e.get("epoch"), e["loss"]] for e in log)
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plt.figure(figsize=(6, 3.5))
        plt.plot([e["step"] for e in log], [e["loss"] for e in log], marker="o")
        plt.xlabel("optimizer step")
        plt.ylabel("training loss")
        plt.title(f"QLoRA smoke: {cfg['base_model']}, {len(rows)} items")
        plt.tight_layout()
        plt.savefig(out / "loss_curve.png", dpi=120)
    except ImportError:
        pass

    (out / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=True), encoding="utf-8")
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    manifest = {
        "run_id": run_id,
        "git_commit": commit,
        "base_model": cfg["base_model"],
        "train_file": cfg["train_file"],
        "train_file_sha256": _sha256(Path(cfg["train_file"])),
        "n_train": len(rows),
        "train_item_ids_sha256": hashlib.sha256("\n".join(r["item_id"] for r in rows).encode()).hexdigest(),
        "class_counts": {c: sum(r["labels"]["triage_level"] == c for r in rows) for c in ("green", "yellow", "red")},
        "unaudited_data": args.allow_unaudited,
        "train_loss": result.training_loss,
        "first_logged_loss": log[0]["loss"] if log else None,
        "last_logged_loss": log[-1]["loss"] if log else None,
        "train_seconds": round(seconds, 1),
        "seconds_per_epoch": round(seconds / cfg["epochs"], 1),
        "compute_dtype": str(cdtype),
        "max_memory_mb": round(torch.cuda.max_memory_allocated() / 2**20) if torch.cuda.is_available() else None,
        "versions": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "transformers": transformers.__version__,
            "peft": peft.__version__,
            "trl": trl.__version__,
            "bitsandbytes": bitsandbytes.__version__,
            "datasets": datasets.__version__,
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        },
    }
    (out / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(out),
                **{
                    k: manifest[k]
                    for k in ("train_loss", "first_logged_loss", "last_logged_loss", "train_seconds", "max_memory_mb")
                },
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

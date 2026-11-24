"""Triage classifier training skeleton: 3-way sequence classification with LoRA (issue F8, plan §6.4).

Not used for real training yet (that is week 10). ``--smoke`` runs end to end on 50 items to prove the pipeline:
load JSONL, tokenize, LoRA-wrap, train a few steps, evaluate red recall / green FPR, and write the run directory.

    python -m src.training.train_classifier --config configs/classifier_smoke.yaml --smoke

Requires the ``ml`` dependency group (torch, transformers, peft, pyyaml). Never point it at ``data/golden/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import time
from pathlib import Path
from typing import Any

import yaml

from src.training.triage_metrics import LABELS, triage_metrics

LABEL2ID = {label: i for i, label in enumerate(LABELS)}  # green=0, yellow=1, red=2
ID2LABEL = dict(enumerate(LABELS))


def load_jsonl(path: Path, limit: int | None = None, seed: int = 0) -> list[dict[str, Any]]:
    """Read triage items; with ``limit``, take a class-stratified, seeded subset."""
    if "golden" in {p.lower() for p in path.resolve().parts}:
        raise ValueError("refusing to read golden data for classifier training")
    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if limit is None or limit >= len(items):
        return items
    rng = random.Random(seed)
    by_label: dict[str, list[dict[str, Any]]] = {label: [] for label in LABELS}
    for it in items:
        by_label[it["label"]].append(it)
    picked: list[dict[str, Any]] = []
    for i, label in enumerate(LABELS):
        share = limit // len(LABELS) + (1 if i < limit % len(LABELS) else 0)
        picked += rng.sample(by_label[label], min(share, len(by_label[label])))
    rng.shuffle(picked)
    return picked


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - needs the ml group and a model download
    """Train (or smoke-test) the classifier and write ``metrics.json``, ``config.yaml``, ``run_manifest.json``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true", help="50 items, a few steps, tiny eval")
    parser.add_argument("--model", help="override base_model (e.g. a tiny model for a pipeline check)")
    args = parser.parse_args(argv)

    import peft
    import torch
    import transformers
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        DataCollatorWithPadding,
        Trainer,
        TrainingArguments,
    )

    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    if args.model:
        cfg["base_model"] = args.model
    if args.smoke:
        cfg.update(cfg.get("smoke", {}))
    transformers.set_seed(cfg["seed"])
    run_id = time.strftime("%Y%m%d-%H%M%S") + ("-smoke" if args.smoke else "")
    out_dir = Path(cfg["output_dir"]) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    train_items = load_jsonl(Path(cfg["train_file"]), cfg.get("train_limit"), cfg["seed"])
    dev_items = load_jsonl(Path(cfg["dev_file"]), cfg.get("dev_limit"), cfg["seed"])

    tok = AutoTokenizer.from_pretrained(cfg["base_model"])
    if tok.pad_token is None:  # Llama/Qwen have no pad token
        tok.pad_token = tok.eos_token
    model = AutoModelForSequenceClassification.from_pretrained(
        cfg["base_model"],
        num_labels=len(LABELS),
        id2label=ID2LABEL,
        label2id=LABEL2ID,
        torch_dtype=torch.float16 if torch.cuda.is_available() and cfg.get("fp16") else torch.float32,
    )
    model.config.pad_token_id = tok.pad_token_id
    lora = LoraConfig(
        task_type=TaskType.SEQ_CLS,
        r=cfg["lora"]["r"],
        lora_alpha=cfg["lora"]["alpha"],
        lora_dropout=cfg["lora"]["dropout"],
        target_modules=cfg["lora"]["target_modules"],
    )
    model = get_peft_model(model, lora)

    class _DS(torch.utils.data.Dataset):
        def __init__(self, items: list[dict[str, Any]]) -> None:
            self.enc = tok([it["text"] for it in items], truncation=True, max_length=cfg["max_length"])
            self.labels = [LABEL2ID[it["label"]] for it in items]

        def __len__(self) -> int:
            return len(self.labels)

        def __getitem__(self, i: int) -> dict[str, Any]:
            return {
                "input_ids": self.enc["input_ids"][i],
                "attention_mask": self.enc["attention_mask"][i],
                "labels": self.labels[i],
            }

    def compute_metrics(pred: Any) -> dict[str, float]:
        y_pred = [ID2LABEL[int(i)] for i in pred.predictions.argmax(-1)]
        y_true = [ID2LABEL[int(i)] for i in pred.label_ids]
        m = triage_metrics(y_true, y_pred)
        return {"red_recall": m["red_recall"] or 0.0, "green_fpr": m["green_fpr"] or 0.0, "macro_f1": m["macro_f1"]}

    targs = TrainingArguments(
        output_dir=str(out_dir / "checkpoints"),
        per_device_train_batch_size=cfg["batch_size"],
        per_device_eval_batch_size=cfg["batch_size"],
        gradient_accumulation_steps=cfg["grad_accum"],
        learning_rate=float(cfg["learning_rate"]),
        num_train_epochs=cfg["epochs"],
        max_steps=cfg.get("max_steps", -1),
        logging_steps=cfg.get("logging_steps", 10),
        eval_strategy="no",
        save_strategy="no",
        fp16=bool(cfg.get("fp16")) and torch.cuda.is_available(),
        report_to=[],
        seed=cfg["seed"],
    )
    trainer = Trainer(
        model=model,
        args=targs,
        train_dataset=_DS(train_items),
        eval_dataset=_DS(dev_items),
        data_collator=DataCollatorWithPadding(tok),
        compute_metrics=compute_metrics,
    )
    t0 = time.time()
    train_out = trainer.train()
    train_seconds = time.time() - t0
    pred = trainer.predict(_DS(dev_items))
    y_pred = [ID2LABEL[int(i)] for i in pred.predictions.argmax(-1)]
    metrics = triage_metrics([it["label"] for it in dev_items], y_pred)
    metrics.update({"train_loss": train_out.training_loss, "train_seconds": round(train_seconds, 1)})
    if not args.smoke:
        model.save_pretrained(out_dir / "adapter")

    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (out_dir / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=True), encoding="utf-8")
    manifest = {
        "run_id": run_id,
        "smoke": args.smoke,
        "base_model": cfg["base_model"],
        "train_file_sha256": _sha256(Path(cfg["train_file"])),
        "dev_file_sha256": _sha256(Path(cfg["dev_file"])),
        "n_train": len(train_items),
        "n_dev": len(dev_items),
        "versions": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "peft": peft.__version__,
            "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        },
        "max_memory_mb": round(torch.cuda.max_memory_allocated() / 2**20) if torch.cuda.is_available() else None,
    }
    (out_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"out_dir": str(out_dir), **{k: metrics[k] for k in ("red_recall", "green_fpr", "macro_f1")}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Fine-tune Depth Anything V2 Small's decoder on GAMUS height above ground (PLAN.md, Phase 5).

The ViT encoder stays frozen; the DPT neck and head learn top-down geometry. The loss is scale-
and-shift invariant, because the model's output has no units: prediction and target are each
normalised by their median and mean absolute deviation, then compared with L1. Training reads
GAMUS train only, and the checkpoint is chosen on GAMUS val; nothing here reads the NAIP/3DEP
LiDAR tiles. Settings live in configs/finetune_gamus.yaml.

    python scripts/finetune_gamus.py        -> data/models/Depth-Anything-V2-Small-gamus/
                                               + training_log.json next to the weights

Try the result with:  python -m evals.run --split quick --config configs/model_gamus.yaml
GAMUS is CC-BY-4.0: credit it wherever the fine-tuned model is used.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import time

import cv2
import numpy as np
import torch
import torch.nn.functional as F
import yaml
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForDepthEstimation

from depthwizard.config import REPO_ROOT, resolve_path
from depthwizard.depth.model import MEAN, PATCH, STD
from evals.datasets.gamus import load_pair, local_stems, select_balanced
from evals.metrics import relative_metrics

CONFIG = REPO_ROOT / "configs" / "finetune_gamus.yaml"
EPS = 1e-6


class GamusCrops(Dataset):
    """Random crops with flips and 90° turns (top-down imagery has no preferred orientation)."""

    def __init__(self, split: str, stems: list[str], crop: int, seed: int):
        self.split, self.stems, self.crop = split, stems, crop
        self.rng = np.random.default_rng(seed)

    def __len__(self) -> int:
        return len(self.stems)

    def __getitem__(self, i: int):
        rgb, agl = load_pair(self.split, self.stems[i])
        h, w = agl.shape
        y, x = self.rng.integers(0, h - self.crop + 1), self.rng.integers(0, w - self.crop + 1)
        rgb, agl = (
            rgb[y : y + self.crop, x : x + self.crop],
            agl[y : y + self.crop, x : x + self.crop],
        )
        k = int(self.rng.integers(0, 4))
        rgb, agl = np.rot90(rgb, k), np.rot90(agl, k)
        if self.rng.random() < 0.5:
            rgb, agl = rgb[:, ::-1], agl[:, ::-1]
        image = torch.from_numpy(np.ascontiguousarray(rgb)).permute(2, 0, 1).float() / 255.0
        image = (image - torch.tensor(MEAN).view(3, 1, 1)) / torch.tensor(STD).view(3, 1, 1)
        return image, torch.from_numpy(np.ascontiguousarray(agl)).float()


def normalise(x: torch.Tensor, valid: torch.Tensor) -> torch.Tensor:
    """Per image: subtract the median, divide by the mean absolute deviation (valid pixels)."""
    out = torch.empty_like(x)
    for b in range(x.shape[0]):
        v = x[b][valid[b]]
        med = v.median()
        scale = (v - med).abs().mean().clamp_min(EPS)
        out[b] = (x[b] - med) / scale
    return out


def ssi_loss(pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    valid = torch.isfinite(target)
    target = torch.nan_to_num(target)
    diff = (normalise(pred, valid) - normalise(target, valid)).abs()
    return diff[valid].mean()


def forward(model, images: torch.Tensor) -> torch.Tensor:
    out = model(pixel_values=images).predicted_depth
    if out.shape[-2:] != images.shape[-2:]:
        out = F.interpolate(out.unsqueeze(1), size=images.shape[-2:], mode="bilinear").squeeze(1)
    return out


@torch.no_grad()
def validate(model, stems: list[str], split: str, long_side: int, device) -> dict:
    model.eval()
    rmse, r = [], []
    for stem in stems:
        rgb, agl = load_pair(split, stem)
        h, w = agl.shape
        side = max(PATCH, round(long_side / PATCH) * PATCH)
        small = cv2.resize(
            rgb, (side, side), interpolation=cv2.INTER_AREA if side < h else cv2.INTER_CUBIC
        )
        x = torch.from_numpy(small).permute(2, 0, 1).float().div(255.0)
        x = ((x - torch.tensor(MEAN).view(3, 1, 1)) / torch.tensor(STD).view(3, 1, 1))[None].to(
            device
        )
        with torch.autocast(
            device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"
        ):
            pred = forward(model, x)[0].float().cpu().numpy()
        m = relative_metrics(cv2.resize(pred, (w, h), interpolation=cv2.INTER_LINEAR), agl)
        rmse.append(m["rmse"])
        r.append(m["pearson_r"])
    model.train()
    return {"scale_aligned_rmse_m": float(np.mean(rmse)), "pearson_r": float(np.mean(r))}


DRY_RUN_TILES = 16  # smoke-test size


def main() -> None:
    parser = argparse.ArgumentParser(prog="python scripts/finetune_gamus.py")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="one short epoch on a few GAMUS val tiles into out/finetune_dry_run (a smoke test)",
    )
    args = parser.parse_args()
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    if args.dry_run:  # exercises the whole loop; the result is thrown away, never used as a model
        cfg.update(
            train_split=cfg["val_split"],
            epochs=1,
            val_tiles=4,
            warmup_steps=1,
            num_workers=0,
            output_dir="out/finetune_dry_run",
        )
    torch.manual_seed(cfg["seed"])
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    base, out_dir = resolve_path(cfg["base_model"]), resolve_path(cfg["output_dir"])
    model = AutoModelForDepthEstimation.from_pretrained(base).to(device)
    for p in model.backbone.parameters():  # the encoder stays frozen
        p.requires_grad = False
    trainable = [p for p in model.parameters() if p.requires_grad]
    print(f"trainable parameters: {sum(p.numel() for p in trainable) / 1e6:.1f} M")

    train_stems = local_stems(cfg["train_split"])
    if args.dry_run:
        train_stems = train_stems[:DRY_RUN_TILES]
    val_stems = select_balanced(local_stems(cfg["val_split"]), cfg["val_tiles"])
    if not train_stems:
        raise SystemExit(
            "No GAMUS train tiles: python -m evals.datasets.gamus download --split train"
        )
    loader = DataLoader(
        GamusCrops(cfg["train_split"], train_stems, cfg["crop_px"], cfg["seed"]),
        batch_size=cfg["batch_size"],
        shuffle=True,
        num_workers=cfg["num_workers"],
        persistent_workers=cfg["num_workers"] > 0,
        drop_last=True,
    )
    steps = cfg["epochs"] * len(loader)
    optimizer = torch.optim.AdamW(
        trainable, lr=cfg["learning_rate"], weight_decay=cfg["weight_decay"]
    )
    schedule = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda s: (
            min(1.0, (s + 1) / cfg["warmup_steps"])
            * 0.5
            * (1 + math.cos(math.pi * min(s, steps) / steps))
        ),
    )

    log = {
        "config": cfg,
        "train_tiles": len(train_stems),
        "val_tiles": len(val_stems),
        "epochs": [],
    }
    baseline = validate(model, val_stems, cfg["val_split"], cfg["val_long_side"], device)
    log["baseline"] = baseline
    print(f"epoch 0 (pretrained): {baseline}")
    best = baseline["scale_aligned_rmse_m"]
    model.train()
    for epoch in range(1, cfg["epochs"] + 1):
        start, losses = time.time(), []
        for images, targets in loader:
            images, targets = images.to(device), targets.to(device)
            with torch.autocast(
                device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"
            ):
                pred = forward(model, images)
            loss = ssi_loss(pred.float(), targets)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            schedule.step()
            losses.append(loss.item())
        val = validate(model, val_stems, cfg["val_split"], cfg["val_long_side"], device)
        entry = {
            "epoch": epoch,
            "train_loss": float(np.mean(losses)),
            "minutes": round((time.time() - start) / 60, 1),
            **val,
        }
        log["epochs"].append(entry)
        print(entry)
        if val["scale_aligned_rmse_m"] < best:  # keep the best epoch, judged on val only
            best = val["scale_aligned_rmse_m"]
            model.save_pretrained(out_dir)
            shutil.copy(base / "preprocessor_config.json", out_dir / "preprocessor_config.json")
            log["best_epoch"] = epoch
    log["best_val_scale_aligned_rmse_m"] = best
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "training_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    if "best_epoch" not in log:
        print("No epoch beat the pretrained model on GAMUS val; nothing saved as a new model.")
    else:
        print(f"best epoch {log['best_epoch']}: val scale-aligned RMSE {best:.3f} m -> {out_dir}")


if __name__ == "__main__":
    main()

"""Depth Anything V2 wrapper.

Output is relative inverse depth: for a top-down image, larger = closer to the camera = taller.
The model loads once per process (the API keeps one instance for its lifetime).
"""

from __future__ import annotations

import logging

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from transformers import AutoModelForDepthEstimation

from depthwizard.config import ModelConfig, resolve_path

log = logging.getLogger(__name__)

PATCH = 14  # ViT patch size; model input sides must be multiples of it
# ImageNet normalisation, as in the Depth Anything V2 image processor.
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)


def resolve_device(name: str) -> torch.device:
    if name == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(name)


class DepthModel:
    def __init__(self, cfg: ModelConfig):
        path = resolve_path(cfg.local_dir)
        if not (path / "config.json").exists():
            raise FileNotFoundError(
                f"Model not found at {path}. "
                "Run `python scripts/fetch_model.py` once (needs internet)."
            )
        self.device = resolve_device(cfg.device)
        self.dtype = torch.float16 if self.device.type == "cuda" and cfg.fp16 else torch.float32
        self.model = AutoModelForDepthEstimation.from_pretrained(path, dtype=self.dtype)
        self.model.to(self.device).eval()
        self.mean = torch.tensor(MEAN, device=self.device).view(1, 3, 1, 1)
        self.std = torch.tensor(STD, device=self.device).view(1, 3, 1, 1)
        log.info("Loaded %s on %s (%s)", path.name, self.describe_device(), self.dtype)

    def describe_device(self) -> str:
        if self.device.type == "cuda":
            return f"cuda:{torch.cuda.get_device_name(self.device)}"
        return "cpu"

    def to_cpu(self) -> None:
        """Fallback after CUDA OOM even at batch size 1: continue in fp32 on the CPU."""
        self.device, self.dtype = torch.device("cpu"), torch.float32
        self.model.to(self.device, dtype=self.dtype)
        self.mean, self.std = self.mean.cpu(), self.std.cpu()
        torch.cuda.empty_cache()

    @torch.inference_mode()
    def predict_batch(self, batch: np.ndarray) -> np.ndarray:
        """(N, H, W, 3) uint8, H and W multiples of 14 -> (N, H, W) float32 inverse depth."""
        x = torch.from_numpy(np.ascontiguousarray(batch)).to(self.device)
        x = x.permute(0, 3, 1, 2).float().div_(255.0)
        x = ((x - self.mean) / self.std).to(self.dtype)
        out = self.model(pixel_values=x).predicted_depth
        if out.ndim == 3:
            out = out.unsqueeze(1)
        if out.shape[-2:] != x.shape[-2:]:
            out = F.interpolate(
                out.float(), size=x.shape[-2:], mode="bilinear", align_corners=False
            )
        return out[:, 0].float().cpu().numpy()

    def predict_resized(self, rgb: np.ndarray, long_side: int) -> np.ndarray:
        """Resize the whole image so its long side is `long_side` (sides snapped to multiples of
        14), predict once, and resize the prediction back to the input shape."""
        h, w = rgb.shape[:2]
        scale = long_side / max(h, w)
        th = max(PATCH, round(h * scale / PATCH) * PATCH)
        tw = max(PATCH, round(w * scale / PATCH) * PATCH)
        interp = cv2.INTER_AREA if th < h else cv2.INTER_CUBIC
        small = cv2.resize(rgb, (tw, th), interpolation=interp)
        pred = self.predict_batch(small[None])[0]
        return cv2.resize(pred, (w, h), interpolation=cv2.INTER_LINEAR)

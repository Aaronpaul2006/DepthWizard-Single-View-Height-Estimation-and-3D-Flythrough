"""Configuration: configs/default.yaml loaded into one dataclass tree.

The YAML is the single source of truth. Dataclass fields carry no defaults, so a key missing
from default.yaml fails loudly instead of silently falling back to a value hidden in code.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, get_type_hints

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "configs" / "default.yaml"


@dataclass
class ModelConfig:
    id: str
    local_dir: str
    device: str
    fp16: bool


@dataclass
class DepthConfig:
    global_long_side: int
    tile_size: int
    tile_stride: int
    batch_size: int
    align_trim_frac: float


@dataclass
class InputConfig:
    rgb_bands: list[int]
    stretch_percentiles: list[float]
    max_long_side: int


@dataclass
class RelativeConfig:
    norm_percentiles: list[float]


@dataclass
class DemConfig:
    copernicus_url: str
    fetch_timeout_s: float
    resampling: str
    cache_subdir: str
    geoid_grid: str


@dataclass
class CalibrationConfig:
    band_sigma_k: float
    huber_delta_m: float
    gcp_min_points: int
    band_coarse_cells: float
    band_min_r: float
    band_min_cells: int
    dem_relief_std_m: float
    prior_percentile: float
    prior_height_m: float


@dataclass
class ExportConfig:
    nodata: float
    viewer_max_dsm_side: int
    viewer_max_ortho_side: int


@dataclass
class ApiConfig:
    cors_origins: list[str]
    max_upload_mb: int


@dataclass
class PathsConfig:
    cache: str
    jobs: str


@dataclass
class Config:
    model: ModelConfig
    depth: DepthConfig
    input: InputConfig
    relative: RelativeConfig
    dem: DemConfig
    calibration: CalibrationConfig
    export: ExportConfig
    api: ApiConfig
    paths: PathsConfig

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_path(path: str | Path) -> Path:
    """Resolve a config path against the repo root unless it is already absolute."""
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def load_config(*overrides: str | Path) -> Config:
    """Load default.yaml, then deep-merge each override YAML over it in order.

    If DEPTHWIZARD_HOME is set (the desktop app sets it to the user's app-data folder), jobs and
    caches are written there instead of into the repo or install folder. Read-only assets (the
    model, the geoid grid, the viewer) stay where the app is."""
    raw = _read_yaml(DEFAULT_CONFIG)
    for path in overrides:
        raw = _merge(raw, _read_yaml(Path(path)))
    cfg = _build(Config, raw, "config")
    home = os.environ.get("DEPTHWIZARD_HOME")
    if home:
        cfg.paths.cache = str(Path(home) / cfg.paths.cache)
        cfg.paths.jobs = str(Path(home) / cfg.paths.jobs)
    return cfg


def _read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _build(cls: type, raw: dict[str, Any], where: str) -> Any:
    hints = get_type_hints(cls)
    unknown = set(raw) - set(hints)
    missing = set(hints) - set(raw)
    if unknown:
        raise ValueError(f"Unknown keys in {where}: {sorted(unknown)}")
    if missing:
        raise ValueError(f"Missing keys in {where}: {sorted(missing)}")
    kwargs = {}
    for key, kind in hints.items():
        value = raw[key]
        path = f"{where}.{key}"
        kwargs[key] = _build(kind, value, path) if is_dataclass(kind) else _check(kind, value, path)
    return cls(**kwargs)


def _check(kind: Any, value: Any, where: str) -> Any:
    """A leaf value must match its annotation; ints are accepted where floats are expected.
    This catches YAML surprises such as 1.0e9, which YAML 1.1 reads as a string (write 1.0e+9)."""
    if kind is float and isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if getattr(kind, "__origin__", None) is list and isinstance(value, list):
        return value
    if isinstance(kind, type) and isinstance(value, kind):
        if not (kind is int and isinstance(value, bool)):
            return value
    raise ValueError(f"{where} must be {getattr(kind, '__name__', kind)}, got {value!r}")

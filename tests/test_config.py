import pytest

from depthwizard.config import Config, _build, load_config


def test_default_config_loads():
    cfg = load_config()
    assert cfg.depth.tile_size % 14 == 0
    assert cfg.depth.global_long_side % 14 == 0
    assert cfg.depth.tile_stride * 2 == cfg.depth.tile_size


def test_unknown_and_missing_keys_fail():
    raw = load_config().to_dict()
    raw["depth"]["typo"] = 1
    with pytest.raises(ValueError, match="Unknown"):
        _build(Config, raw, "config")
    raw = load_config().to_dict()
    del raw["model"]["fp16"]
    with pytest.raises(ValueError, match="Missing"):
        _build(Config, raw, "config")

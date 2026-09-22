import pytest

from depthwizard.config import Config, _build, load_config


def test_numbers_that_yaml_read_as_text_are_rejected():
    raw = load_config().to_dict()
    raw["calibration"]["dem_relief_std_m"] = "1.0e9"  # what YAML 1.1 makes of 1.0e9
    with pytest.raises(ValueError, match="dem_relief_std_m"):
        _build(Config, raw, "config")


def test_ints_are_accepted_where_floats_are_expected():
    raw = load_config().to_dict()
    raw["calibration"]["dem_relief_std_m"] = 15
    assert _build(Config, raw, "config").calibration.dem_relief_std_m == 15.0


def test_the_shipped_config_is_well_typed():
    cfg = load_config()
    assert isinstance(cfg.calibration.dem_relief_std_m, float)
    assert isinstance(cfg.depth.tile_size, int) and isinstance(cfg.model.fp16, bool)

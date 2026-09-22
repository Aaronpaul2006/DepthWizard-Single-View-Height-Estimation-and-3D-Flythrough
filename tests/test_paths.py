from pathlib import Path

from depthwizard.config import load_config, resolve_path


def test_depthwizard_home_moves_only_writable_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("DEPTHWIZARD_HOME", str(tmp_path))
    cfg = load_config()
    assert resolve_path(cfg.paths.jobs) == tmp_path / "data" / "jobs"
    assert resolve_path(cfg.paths.cache).is_relative_to(tmp_path)
    assert not Path(cfg.model.local_dir).is_absolute()  # read-only assets stay with the app
    assert not Path(cfg.dem.geoid_grid).is_absolute()


def test_without_home_everything_stays_in_the_repo(monkeypatch):
    monkeypatch.delenv("DEPTHWIZARD_HOME", raising=False)
    assert load_config().paths.jobs == "data/jobs"

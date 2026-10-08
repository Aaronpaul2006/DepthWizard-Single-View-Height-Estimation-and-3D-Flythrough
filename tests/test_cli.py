"""The CLI must hand --dem, --gcps and --offline to the pipeline (they were once dropped)."""

import depthwizard.__main__ as cli


def test_cli_passes_dem_gcps_and_offline(monkeypatch, tmp_path):
    seen = {}

    class Result:
        files = {}

    def fake_run(input_path, out_dir, cfg, **kwargs):
        seen.update(kwargs, input=input_path, out=out_dir)
        return Result()

    monkeypatch.setattr(cli, "run", fake_run)
    cli.main(
        [
            "run",
            "--input",
            "a.tif",
            "--out",
            str(tmp_path),
            "--dem",
            "cdnf43a.tif",
            "--gcps",
            "g.csv",
            "--offline",
        ]
    )
    assert seen["dem_path"] == "cdnf43a.tif" and seen["gcps_path"] == "g.csv"
    assert seen["allow_fetch"] is False
    cli.main(["run", "--input", "a.tif", "--out", str(tmp_path)])
    assert seen["dem_path"] is None and seen["allow_fetch"] is True

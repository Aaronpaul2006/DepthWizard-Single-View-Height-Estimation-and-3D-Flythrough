from pathlib import Path

from depthwizard.calibrate.dem import copernicus_tile_names, dem_files, infer_source


def test_infer_source_recognises_bhuvan_tiles_and_folder_names():
    assert infer_source(Path("job/input/dem/cdng45e.tif")) == "cartodem"
    assert infer_source(Path("data/dem/cartodem/tile.tif")) == "cartodem"
    assert infer_source(Path("Copernicus_DSM_COG_10_N27_00_E088_00_DEM.tif")) == "copernicus_glo30"
    assert infer_source(Path("mystery.tif")) == "mystery"


def test_dem_files_finds_tiles_inside_unzipped_subfolders(tmp_path):
    (tmp_path / "cdng45e_v3r1").mkdir()
    (tmp_path / "cdng45e_v3r1" / "cdng45e.tif").write_bytes(b"")
    (tmp_path / "cdng45e_v3r1" / "readme.txt").write_text("not a DEM")
    assert [p.name for p in dem_files(tmp_path)] == ["cdng45e.tif"]


def test_copernicus_tiles_are_named_after_their_south_west_corner():
    assert copernicus_tile_names(88.30, 27.10, 88.42, 27.21) == [
        "Copernicus_DSM_COG_10_N27_00_E088_00_DEM"
    ]
    assert copernicus_tile_names(-105.01, 39.70, -104.90, 39.80) == [
        "Copernicus_DSM_COG_10_N39_00_W106_00_DEM",
        "Copernicus_DSM_COG_10_N39_00_W105_00_DEM",
    ]

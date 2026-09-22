# PyInstaller spec: the DepthWizard backend (FastAPI + depth model + built viewer), one folder.
#
#   .venv\Scripts\pyinstaller desktop\backend.spec --distpath dist --workpath build\pyinstaller
#
# Output: dist\depthwizard-backend\depthwizard-backend.exe plus _internal\. depthwizard.config
# resolves REPO_ROOT to _internal\, so configs, the model, the geoid grid and the viewer are placed
# there with the same relative paths as in the repo. Writable data (jobs, DEM cache) goes to
# DEPTHWIZARD_HOME, which the desktop shell sets to the user's app-data folder.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent

datas = [
    (str(ROOT / "configs"), "configs"),
    (str(ROOT / "viewer" / "dist"), "viewer/dist"),
    (str(ROOT / "data" / "models"), "data/models"),
    (str(ROOT / "data" / "geoid"), "data/geoid"),
]
datas += collect_data_files("rasterio")  # GDAL data files
datas += collect_data_files("pyproj")  # PROJ database

hiddenimports = (
    collect_submodules("api")
    + collect_submodules("depthwizard")
    + collect_submodules("evals")
    + collect_submodules("uvicorn")
    # imported at runtime from compiled or lazy modules, so PyInstaller's analysis misses them
    + collect_submodules("rasterio")  # e.g. rasterio._base imports rasterio.serde
    + collect_submodules("pyproj")
    + collect_submodules("transformers.models.depth_anything")
    + ["multipart"]
)

a = Analysis(
    [str(ROOT / "scripts" / "serve.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["matplotlib", "tkinter", "IPython", "pytest", "planetary_computer", "pystac_client"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="depthwizard-backend",
    console=True,  # the shell hides the window; uvicorn needs a real stdout to log to
)
coll = COLLECT(exe, a.binaries, a.datas, name="depthwizard-backend")

# DepthWizard desktop app

A Tauri 2 window around the local backend. On start it launches the bundled backend
(`depthwizard-backend.exe --port 8765 --no-browser`, jobs and caches in the user's app-data folder),
shows `splash/index.html` until the depth model has loaded, then opens the viewer the backend
serves. Closing the window stops the backend.

## Why a portable folder, not an installer

The backend bundles PyTorch with CUDA, which is several GB. NSIS and MSI installers struggle past
2 GB, so the app ships as a folder (or a zip of it):

```
DepthWizard/
  depthwizard.exe          Tauri shell
  backend/                 PyInstaller one-folder backend (depthwizard-backend.exe + _internal/)
```

Needs WebView2 (built into Windows 11). A GPU is optional; without one the model runs on the CPU.

## Build (Windows)

Prerequisites: the one-time setup in the root README, Rust (`rustup`, stable-msvc), and
Visual Studio Build Tools with the C++ workload.

```powershell
cd viewer; npm ci; npm run build; cd ..
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\pyinstaller desktop\backend.spec --distpath dist --workpath build\pyinstaller --noconfirm
cd desktop; npm ci; npx tauri icon ..\docs\assets\icon.png; npx tauri build --no-bundle; cd ..
powershell -File desktop\package_portable.ps1
```

The last step assembles `dist\DepthWizard\` from the two builds.

If the app runs into trouble, the web mode is the fallback: `run_local.bat`.

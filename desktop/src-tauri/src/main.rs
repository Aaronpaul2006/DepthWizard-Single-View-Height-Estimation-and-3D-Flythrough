// DepthWizard desktop shell (Tauri 2). It starts the bundled Python backend on 127.0.0.1:8765,
// shows splash/index.html until the depth model has loaded, then the window opens the viewer
// the backend serves. The backend is stopped when the app exits.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::{Manager, RunEvent};

// docs/VIEWER_CONTRACT.md: inside the desktop app the backend listens on 127.0.0.1:8765.
const BACKEND_PORT: &str = "8765";

struct Backend(Mutex<Option<Child>>);

/// The PyInstaller one-folder backend: next to the app (portable build) or in its resources.
fn backend_exe(app: &tauri::AppHandle) -> Option<PathBuf> {
    let name = if cfg!(windows) { "depthwizard-backend.exe" } else { "depthwizard-backend" };
    let beside = std::env::current_exe().ok()?.parent()?.join("backend").join(name);
    if beside.exists() {
        return Some(beside);
    }
    let bundled = app.path().resource_dir().ok()?.join("backend").join(name);
    bundled.exists().then_some(bundled)
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let exe = backend_exe(app.handle())
                .ok_or("The DepthWizard backend folder was not found next to the app.")?;
            // Jobs and caches go to the user's app-data folder, never into the install folder.
            let home = app.path().app_local_data_dir()?;
            std::fs::create_dir_all(&home)?;
            let mut command = Command::new(exe);
            command
                .args(["--port", BACKEND_PORT, "--no-browser"])
                .env("DEPTHWIZARD_HOME", &home);
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                const CREATE_NO_WINDOW: u32 = 0x0800_0000; // no console window for the backend
                command.creation_flags(CREATE_NO_WINDOW);
            }
            app.manage(Backend(Mutex::new(Some(command.spawn()?))));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the DepthWizard window")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(mut child) = app.state::<Backend>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}

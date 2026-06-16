//! Ember Code desktop shell.
//!
//! Spawns the Python backend (`python -m ember_code.backend --ws-port 0`),
//! waits for its JSON ready line to learn the bound WebSocket port, then
//! opens the shared web UI (clients/web) pointed at that port via the
//! `?ws=` query param. The backend self-terminates if this process dies
//! (EMBER_PARENT_PID watchdog), and we also kill it on window close.

use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

struct BackendHandle(Mutex<Option<Child>>);

/// Spawn the backend and block until its ready line reports the WS port.
fn spawn_backend(project_dir: &str) -> Result<(Child, u16), String> {
    // EMBER_PYTHON lets users point at a venv; default to PATH python3.
    let python = std::env::var("EMBER_PYTHON").unwrap_or_else(|_| "python3".to_string());
    let mut child = Command::new(&python)
        .args([
            "-m",
            "ember_code.backend",
            "--ws-port",
            "0",
            "--project-dir",
            project_dir,
        ])
        .env("EMBER_PARENT_PID", std::process::id().to_string())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("failed to spawn backend via `{python}`: {e}"))?;

    let stdout = child.stdout.take().ok_or("backend stdout unavailable")?;
    let mut reader = BufReader::new(stdout);
    let mut line = String::new();
    let port = loop {
        line.clear();
        let n = reader
            .read_line(&mut line)
            .map_err(|e| format!("backend stdout read failed: {e}"))?;
        if n == 0 {
            return Err("backend exited before signalling ready".to_string());
        }
        if let Ok(v) = serde_json::from_str::<serde_json::Value>(line.trim()) {
            if v["status"] == "ready" {
                match v["ws_port"].as_u64() {
                    Some(p) => break p as u16,
                    None => return Err("ready line missing ws_port".to_string()),
                }
            }
        }
    };

    // Keep draining stdout so the backend never blocks on a full pipe.
    std::thread::spawn(move || {
        let mut sink = String::new();
        while let Ok(n) = reader.read_line(&mut sink) {
            if n == 0 {
                break;
            }
            sink.clear();
        }
    });

    Ok((child, port))
}

fn project_dir() -> String {
    // CLI arg wins; fall back to cwd (launching from a project root).
    std::env::args()
        .nth(1)
        .unwrap_or_else(|| ".".to_string())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            let dir = project_dir();
            let (child, port) = spawn_backend(&dir).map_err(|e| -> Box<dyn std::error::Error> {
                format!("Ember backend failed to start: {e}").into()
            })?;
            app.manage(BackendHandle(Mutex::new(Some(child))));

            let url = format!("index.html?ws=ws%3A%2F%2F127.0.0.1%3A{port}");
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App(url.into()))
                .title("Ember Code")
                .inner_size(1100.0, 780.0)
                // Native folder picker for the web UI's project-lock
                // chip — the in-app directory browser is only the
                // plain-browser fallback.
                .initialization_script(
                    r#"window.__EMBER_PICK_DIR__ = (start) =>
                        window.__TAURI__.core.invoke('plugin:dialog|open', {
                            options: {
                                directory: true,
                                multiple: false,
                                defaultPath: start || undefined
                            }
                        });
                    // Native open-file bridge for host.openFile in the FE.
                    // Routes through the opener plugin so files open in
                    // the user's default OS app (their editor, image
                    // viewer, etc.) rather than the in-app preview.
                    window.__EMBER_HOST__ = Object.assign(window.__EMBER_HOST__ || {}, {
                        openFile: (path) => window.__TAURI__.core.invoke(
                            'plugin:opener|open_path', { path }
                        ),
                        revealInFolder: (path) => window.__TAURI__.core.invoke(
                            'plugin:opener|reveal_item_in_dir', { path }
                        ),
                        // OS-banner notifications for host.notify in the FE.
                        // Used for scheduled-task completions when the
                        // app is backgrounded.
                        notify: (payload) => window.__TAURI__.core.invoke(
                            'plugin:notification|notify',
                            { options: { title: payload.title, body: payload.body || '' } }
                        ),
                    });"#,
                )
                .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Ember Code app")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(handle) = app.try_state::<BackendHandle>() {
                    if let Some(mut child) = handle.0.lock().unwrap().take() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        });
}

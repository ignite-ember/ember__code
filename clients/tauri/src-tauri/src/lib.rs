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

use tauri::menu::{AboutMetadata, Menu, MenuBuilder, MenuItem, PredefinedMenuItem, Submenu};
use tauri::{Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

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
        if let Some(p) = parse_ready_line(&line) {
            break p;
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

/// Parse a single stdout line from the backend and return the bound
/// WebSocket port if and only if it's the JSON ready handshake.
///
/// The BE emits assorted log lines on stdout during startup; only the
/// ``{"status": "ready", "ws_port": N, ...}`` envelope signals it's
/// ready to accept connections. Returning ``None`` for non-ready lines
/// lets the read loop keep draining instead of failing.
///
/// Extracted from the spawn path so unit tests can exercise the parse
/// without spawning a real BE.
fn parse_ready_line(line: &str) -> Option<u16> {
    let v: serde_json::Value = serde_json::from_str(line.trim()).ok()?;
    if v["status"] != "ready" {
        return None;
    }
    v["ws_port"].as_u64().map(|p| p as u16)
}

/// Build the native menu bar.
///
/// On macOS the menu lives in the menu bar (top of screen); on Linux
/// / Windows it lives in the window's titlebar. The standard items
/// (Quit, Hide, Edit's Cut/Copy/Paste, Window's Close/Minimise) come
/// from ``PredefinedMenuItem`` so they automatically get the right
/// shortcut for the platform and the right localisation.
///
/// Custom items emit ``menu`` events the JS side picks up by id —
/// see the ``on_menu_event`` registration after the builder. We use
/// this for app-specific actions (New Chat, Restart Backend) that
/// the FE handles via ``window.addEventListener('ember-host', …)``.
fn build_menu(app: &tauri::AppHandle) -> tauri::Result<Menu<tauri::Wry>> {
    // ── App / About menu (macOS-only — Linux/Windows merge it into Help) ──
    let app_meta = AboutMetadata {
        name: Some("Ember Code".into()),
        copyright: Some("© 2026 Ignite Ember".into()),
        website: Some("https://ignite-ember.sh".into()),
        ..Default::default()
    };
    let about = PredefinedMenuItem::about(app, Some("About Ember Code"), Some(app_meta))?;
    let services = PredefinedMenuItem::services(app, None)?;
    let hide = PredefinedMenuItem::hide(app, None)?;
    let hide_others = PredefinedMenuItem::hide_others(app, None)?;
    let show_all = PredefinedMenuItem::show_all(app, None)?;
    let quit = PredefinedMenuItem::quit(app, None)?;
    let app_menu = Submenu::with_items(
        app,
        "Ember Code",
        true,
        &[
            &about,
            &PredefinedMenuItem::separator(app)?,
            &services,
            &PredefinedMenuItem::separator(app)?,
            &hide,
            &hide_others,
            &show_all,
            &PredefinedMenuItem::separator(app)?,
            &quit,
        ],
    )?;

    // ── File ──
    let new_chat = MenuItem::with_id(
        app,
        "new_chat",
        "New Chat",
        true,
        Some("CmdOrCtrl+N"),
    )?;
    let restart_backend = MenuItem::with_id(
        app,
        "restart_backend",
        "Restart Backend",
        true,
        Some("CmdOrCtrl+Shift+R"),
    )?;
    let close_window = PredefinedMenuItem::close_window(app, None)?;
    let file_menu = Submenu::with_items(
        app,
        "File",
        true,
        &[
            &new_chat,
            &restart_backend,
            &PredefinedMenuItem::separator(app)?,
            &close_window,
        ],
    )?;

    // ── Edit ──
    let edit_menu = Submenu::with_items(
        app,
        "Edit",
        true,
        &[
            &PredefinedMenuItem::undo(app, None)?,
            &PredefinedMenuItem::redo(app, None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::cut(app, None)?,
            &PredefinedMenuItem::copy(app, None)?,
            &PredefinedMenuItem::paste(app, None)?,
            &PredefinedMenuItem::select_all(app, None)?,
        ],
    )?;

    // ── View ──
    let toggle_devtools = MenuItem::with_id(
        app,
        "toggle_devtools",
        "Toggle Developer Tools",
        true,
        Some("CmdOrCtrl+Alt+I"),
    )?;
    let view_menu = Submenu::with_items(
        app,
        "View",
        true,
        &[
            &PredefinedMenuItem::fullscreen(app, None)?,
            &toggle_devtools,
        ],
    )?;

    // ── Window ──
    let window_menu = Submenu::with_items(
        app,
        "Window",
        true,
        &[
            &PredefinedMenuItem::minimize(app, None)?,
            &PredefinedMenuItem::maximize(app, None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::close_window(app, None)?,
        ],
    )?;

    MenuBuilder::new(app)
        .items(&[&app_menu, &file_menu, &edit_menu, &view_menu, &window_menu])
        .build()
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            // Native menu — has to be set before the first window
            // builds or macOS shows the default Tauri stub.
            let menu = build_menu(&app.handle())?;
            app.set_menu(menu)?;

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
                    });
                    // Native-menu → FE bridge. The Rust side emits
                    // ``ember-menu`` Tauri events when the user
                    // clicks a custom menu item (New Chat, Restart
                    // Backend); we re-emit them as the same
                    // ``ember-host`` CustomEvents the rest of the
                    // app already handles, so the FE doesn't grow
                    // a third event source. ``listen`` returns
                    // an unlisten function we discard — Tauri tears
                    // it down on window close anyway.
                    if (window.__TAURI__ && window.__TAURI__.event) {
                        window.__TAURI__.event.listen('ember-menu', (e) => {
                            const id = e && e.payload;
                            if (typeof id !== 'string') return;
                            window.dispatchEvent(new CustomEvent('ember-host', {
                                detail: { type: 'ember:menu', payload: { id } }
                            }));
                        });
                    }"#,
                )
                .build()?;
            Ok(())
        })
        // Native menu items emit ``ember-menu`` events on the
        // ``main`` webview; the FE picks them up via
        // ``window.addEventListener('ember-menu', e => …)`` and
        // routes them through the existing host-bridge dispatcher
        // (same handler as the JetBrains ``ember-host`` events,
        // just on a separate channel because Tauri's emit format
        // and JCEF's CustomEvent shape don't line up cleanly).
        .on_menu_event(|app, event| match event.id().as_ref() {
            "toggle_devtools" => {
                if let Some(w) = app.get_webview_window("main") {
                    #[cfg(debug_assertions)]
                    {
                        if w.is_devtools_open() {
                            w.close_devtools();
                        } else {
                            w.open_devtools();
                        }
                    }
                    #[cfg(not(debug_assertions))]
                    {
                        // Devtools are stripped from release builds;
                        // surface a no-op so the menu item stays
                        // visible but doesn't appear broken.
                        let _ = w;
                    }
                }
            }
            id => {
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.emit("ember-menu", id.to_string());
                }
            }
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ready_line_parsed_returns_port() {
        assert_eq!(
            parse_ready_line(r#"{"status":"ready","ws_port":51234}"#),
            Some(51234),
        );
    }

    #[test]
    fn ready_line_with_extra_fields_ok() {
        // The BE includes extra fields (socket path, session id, …)
        // alongside the ready signal. We only care about ws_port.
        assert_eq!(
            parse_ready_line(
                r#"{"status":"ready","ws_port":8080,"socket":"/tmp/x.sock"}"#,
            ),
            Some(8080),
        );
    }

    #[test]
    fn trailing_newline_doesnt_break_parse() {
        assert_eq!(
            parse_ready_line("{\"status\":\"ready\",\"ws_port\":1}\n"),
            Some(1),
        );
    }

    #[test]
    fn non_ready_status_returns_none() {
        // BE logs other JSON status events too (e.g. warmup); they
        // must not be confused for "ready".
        assert_eq!(
            parse_ready_line(r#"{"status":"starting","ws_port":1234}"#),
            None,
        );
    }

    #[test]
    fn non_json_line_returns_none() {
        // stderr-style log lines on stdout shouldn't crash the loop.
        assert_eq!(parse_ready_line("INFO loading sessions..."), None);
    }

    #[test]
    fn missing_ws_port_returns_none() {
        // Ready without a port is malformed — don't break to a bogus
        // value, just keep reading.
        assert_eq!(parse_ready_line(r#"{"status":"ready"}"#), None);
    }
}


# Ember Code — standalone desktop app (Tauri v2)

Thin native shell around the shared web UI (`clients/web`). On launch it:

1. spawns `python -m ember_code.backend --ws-port 0 --project-dir <arg or cwd>`
   (override the interpreter with `EMBER_PYTHON=/path/to/venv/bin/python`),
2. reads the backend's JSON ready line to learn the bound WS port,
3. opens the web UI pointed at `ws://127.0.0.1:<port>`.

The backend is killed on app exit and also self-terminates if the app
dies (EMBER_PARENT_PID watchdog).

## Prerequisites

- Rust toolchain (`rustup`), see https://v2.tauri.app/start/prerequisites/
- Node 20+ (builds `clients/web`)
- `ignite-ember` installed in the Python the app spawns

## Dev

```bash
cd clients/web && npm install && npm run build
cd ../tauri/src-tauri && cargo tauri dev   # or: cargo run
```

Pass a project directory: `cargo run -- /path/to/project`.

## Build

```bash
cd clients/tauri/src-tauri && cargo tauri build
```

> NOTE: not compiled in CI yet — requires the Rust toolchain. The web UI
> and backend protocol it embeds are covered by tests; the Rust shell is
> ~100 lines of spawn/window glue.

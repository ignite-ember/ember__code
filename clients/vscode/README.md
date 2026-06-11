# Ember Code — VSCode extension

Hosts the shared web UI (`clients/web`) in a webview panel; spawns the
Python backend for the open workspace over a loopback WebSocket.

## Build

```bash
cd clients/vscode
npm install
npm run build       # builds ../web, copies dist → media/, compiles TS
```

Run with F5 (Extension Development Host), then `Ember Code: Open Chat`
from the command palette.

Set `emberCode.pythonPath` if `ignite-ember` lives in a venv.

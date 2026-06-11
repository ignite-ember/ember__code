/**
 * Ember Code VSCode extension.
 *
 * Hosts the shared web UI (clients/web, bundled into ./media) in a
 * webview panel and spawns the Python backend for the open workspace:
 * `python -m ember_code.backend --ws-port 0`. The webview connects
 * straight to the backend's loopback WebSocket — the extension only
 * does process lifecycle + asset rewriting.
 */

import { ChildProcess, spawn } from "child_process";
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";

let backend: ChildProcess | undefined;
let backendPort: number | undefined;
let panel: vscode.WebviewPanel | undefined;

function startBackend(projectDir: string): Promise<number> {
  const python = vscode.workspace
    .getConfiguration("emberCode")
    .get<string>("pythonPath", "python3");

  return new Promise((resolve, reject) => {
    const child = spawn(
      python,
      ["-m", "ember_code.backend", "--ws-port", "0", "--project-dir", projectDir],
      {
        env: { ...process.env, EMBER_PARENT_PID: String(process.pid) },
        stdio: ["ignore", "pipe", "pipe"],
      },
    );

    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Ember backend did not become ready within 120s"));
    }, 120_000);

    let buf = "";
    child.stdout.on("data", (chunk: Buffer) => {
      buf += chunk.toString();
      let nl: number;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        try {
          const obj = JSON.parse(line);
          if (obj.status === "ready" && obj.ws_port) {
            clearTimeout(timer);
            backend = child;
            backendPort = obj.ws_port;
            resolve(obj.ws_port);
            return;
          }
        } catch {
          /* non-JSON startup noise (warnings) — skip */
        }
      }
    });
    child.stderr.on("data", () => {
      /* backend logs to ~/.ember/debug.log; stderr is noise here */
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (backendPort === undefined) {
        reject(new Error(`Ember backend exited during startup (code ${code})`));
      }
      backend = undefined;
      backendPort = undefined;
    });
  });
}

function buildHtml(webview: vscode.Webview, extensionUri: vscode.Uri, wsPort: number): string {
  const mediaRoot = vscode.Uri.joinPath(extensionUri, "media");
  let html = fs.readFileSync(path.join(mediaRoot.fsPath, "index.html"), "utf8");

  // Rewrite relative asset refs to webview-safe URIs.
  html = html.replace(
    /(src|href)="\.\/(assets\/[^"]+)"/g,
    (_m, attr: string, p: string) =>
      `${attr}="${webview.asWebviewUri(vscode.Uri.joinPath(mediaRoot, p))}"`,
  );

  // CSP: scripts/styles from the extension bundle, WS to loopback only.
  const csp = [
    `default-src 'none'`,
    `style-src ${webview.cspSource} 'unsafe-inline'`,
    `script-src ${webview.cspSource}`,
    `font-src ${webview.cspSource}`,
    `img-src ${webview.cspSource} data:`,
    `connect-src ws://127.0.0.1:${wsPort}`,
  ].join("; ");

  html = html.replace(
    "<head>",
    `<head>\n<meta http-equiv="Content-Security-Policy" content="${csp}">` +
      `\n<script>window.__EMBER_WS_URL__ = "ws://127.0.0.1:${wsPort}";</script>`,
  );
  return html;
}

export function activate(context: vscode.ExtensionContext) {
  context.subscriptions.push(
    vscode.commands.registerCommand("emberCode.open", async () => {
      if (panel) {
        panel.reveal();
        return;
      }
      const folder =
        vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? process.cwd();

      let port: number;
      try {
        port =
          backendPort ??
          (await vscode.window.withProgress(
            {
              location: vscode.ProgressLocation.Notification,
              title: "Starting Ember Code backend…",
            },
            () => startBackend(folder),
          ));
      } catch (e) {
        vscode.window.showErrorMessage(String(e));
        return;
      }

      panel = vscode.window.createWebviewPanel(
        "emberCode",
        "Ember Code",
        vscode.ViewColumn.Beside,
        {
          enableScripts: true,
          retainContextWhenHidden: true,
          localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, "media")],
        },
      );
      panel.webview.html = buildHtml(panel.webview, context.extensionUri, port);
      panel.onDidDispose(() => {
        panel = undefined;
        // Backend stays up for fast re-open; killed on deactivate.
      });
    }),
  );
}

export function deactivate() {
  backend?.kill();
  backend = undefined;
  backendPort = undefined;
}

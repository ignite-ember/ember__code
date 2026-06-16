/**
 * Managed-runtime bootstrap for the Ember backend.
 *
 * Mirrors ``EmberRuntime.kt`` from the JetBrains plugin: on first
 * launch we download the ``uv`` binary for the current OS/arch, use
 * it to provision a pinned Python and install ``ignite-ember`` into
 * a managed venv, and return the venv's Python path. Subsequent
 * launches reuse the cache directly (sub-100ms overhead).
 *
 * Cache layout under the extension's globalStorage:
 *
 *   <globalStorage>/
 *     uv (or uv.exe on Windows)        ← downloaded once
 *     venv/                            ← per-plugin-version
 *       bin/python | Scripts/python.exe
 *     ember-install.json               ← marker recording installed versions
 *
 * **Dev override.** Setting ``EMBER_DEV_BACKEND=/abs/path/to/python``
 * bypasses the bootstrap and returns that path verbatim. The
 * ``emberCode.pythonPath`` user setting is honored the same way —
 * for users who want to point at their own venv (e.g. ember-code
 * contributors running an editable install). Both paths skip every
 * download + install step.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { spawn } from "node:child_process";
import { IGNITE_EMBER_VERSION } from "./version.generated";

const PYTHON_VERSION = "3.12";
const UV_VERSION = "0.5.7";
const INSTALL_MARKER = "ember-install.json";

export type ProgressFn = (msg: string) => void;

export interface RuntimeOptions {
  /** Where the cache lives. Pass ``context.globalStorageUri.fsPath``. */
  cacheDir: string;
  /** User-configured python (``emberCode.pythonPath``). Honored if set; bootstrap skipped. */
  configuredPython?: string;
  /** Progress hook for the long-running download/install steps. */
  onProgress?: ProgressFn;
}

/** Result of [ensureBackendPython]: the Python to spawn the BE with,
 *  plus environment variables to layer onto the BE process.
 *  ``HF_HOME`` keeps HuggingFace's cache inside the managed
 *  directory so a clean reinstall really wipes everything. */
export interface BackendInstall {
  python: string;
  env: Record<string, string>;
}

/**
 * Resolve a Python interpreter with ``ignite-ember`` installed AND
 * the sentence-transformer embedding model pre-warmed. Bootstraps on
 * first call; returns cached on subsequent calls. Throws if anything
 * goes wrong (caller surfaces via ``vscode.window.showErrorMessage``).
 */
export async function ensureBackendPython(opts: RuntimeOptions): Promise<BackendInstall> {
  const log = opts.onProgress ?? (() => {});

  // ── Dev / user override ──
  const dev = process.env.EMBER_DEV_BACKEND?.trim();
  if (dev) return { python: dev, env: {} };
  if (opts.configuredPython && opts.configuredPython.trim()) {
    return { python: opts.configuredPython.trim(), env: {} };
  }

  await fs.promises.mkdir(opts.cacheDir, { recursive: true });
  const hfHome = path.join(opts.cacheDir, "huggingface");

  const uvPath = path.join(opts.cacheDir, isWindows() ? "uv.exe" : "uv");
  const markerPath = path.join(opts.cacheDir, INSTALL_MARKER);
  const venvDir = path.join(opts.cacheDir, "venv");
  const venvPython = path.join(
    venvDir,
    isWindows() ? "Scripts/python.exe" : "bin/python",
  );

  const wantMarker = JSON.stringify({
    uv: UV_VERSION,
    python: PYTHON_VERSION,
    ignite: IGNITE_EMBER_VERSION,
  });
  const haveMarker = await readFileOrNull(markerPath);

  // ── 1. uv binary ──
  if (!(await isExecutable(uvPath)) || haveMarker !== wantMarker) {
    log("Downloading uv (one-time, ~25 MB)…");
    await downloadUv(uvPath);
  }

  // ── 2. Python + 3. venv + 4. ignite-ember + 5. prefetch ──
  if (!(await isExecutable(venvPython)) || haveMarker !== wantMarker) {
    if (await pathExists(venvDir)) {
      log("Refreshing managed venv…");
      await fs.promises.rm(venvDir, { recursive: true, force: true });
    }
    log(`Installing Python ${PYTHON_VERSION} (one-time)…`);
    await runUv(uvPath, ["python", "install", PYTHON_VERSION]);

    log("Creating backend venv…");
    await runUv(uvPath, ["venv", "--python", PYTHON_VERSION, venvDir]);

    log("Installing ignite-ember (one-time)…");
    await runUv(uvPath, [
      "pip",
      "install",
      "--python",
      venvPython,
      `ignite-ember==${IGNITE_EMBER_VERSION}`,
    ]);

    // Pre-warm the sentence-transformer cache so the first agent
    // run doesn't stall mid-chat on a silent 90 MB HuggingFace
    // download.
    log("Downloading embedding model (one-time, ~90 MB)…");
    await runProcess(venvPython, ["-m", "ember_code.prefetch_models"], {
      env: { HF_HOME: hfHome },
      timeoutMs: 10 * 60_000,
    });

    await fs.promises.writeFile(markerPath, wantMarker);
  }

  return { python: venvPython, env: { HF_HOME: hfHome } };
}

/** Wipe the entire managed cache. Used by ``emberCode.reinstall``. */
export async function resetCache(cacheDir: string): Promise<void> {
  if (await pathExists(cacheDir)) {
    await fs.promises.rm(cacheDir, { recursive: true, force: true });
  }
}

// ── Platform + downloads ───────────────────────────────────────────

function isWindows(): boolean {
  return process.platform === "win32";
}

/** GitHub-release asset triple for the current OS/arch. */
function uvTarget(): string {
  const arch = process.arch;
  switch (process.platform) {
    case "darwin":
      return arch === "arm64" ? "aarch64-apple-darwin" : "x86_64-apple-darwin";
    case "linux":
      return arch === "arm64" ? "aarch64-unknown-linux-gnu" : "x86_64-unknown-linux-gnu";
    case "win32":
      return "x86_64-pc-windows-msvc";
    default:
      throw new Error(`Unsupported platform: ${process.platform}/${arch}`);
  }
}

async function downloadUv(dest: string): Promise<void> {
  const triple = uvTarget();
  const ext = isWindows() ? "zip" : "tar.gz";
  const url =
    `https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${triple}.${ext}`;
  const tmp = path.join(os.tmpdir(), `uv-${Date.now()}.${ext}`);

  try {
    await downloadFile(url, tmp);
    await extractUv(tmp, dest, ext);
  } finally {
    fs.promises.unlink(tmp).catch(() => {});
  }
}

async function downloadFile(url: string, dest: string): Promise<void> {
  // Follow redirects manually — GitHub releases redirect via 302
  // to a signed S3 URL, and Node's ``fetch`` follows by default
  // since 18 but the typing isn't always reliable in our @types
  // version. Using ``fetch`` is the simplest path.
  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok || !res.body) {
    throw new Error(`uv download failed: HTTP ${res.status} from ${url}`);
  }
  const file = fs.createWriteStream(dest);
  // Stream the response body to disk. Node 18+ ``Response.body`` is
  // a web ReadableStream; ``pipeline`` from node:stream/promises
  // handles the conversion.
  const reader = (res.body as ReadableStream<Uint8Array>).getReader();
  await new Promise<void>((resolve, reject) => {
    file.on("error", reject);
    file.on("finish", resolve);
    (async () => {
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          if (!file.write(Buffer.from(value))) {
            await new Promise<void>((r) => file.once("drain", r));
          }
        }
        file.end();
      } catch (e) {
        file.destroy(e as Error);
      }
    })();
  });
}

async function extractUv(archive: string, dest: string, ext: string): Promise<void> {
  await fs.promises.mkdir(path.dirname(dest), { recursive: true });
  if (ext === "zip") {
    // Windows zip — defer to PowerShell's Expand-Archive to avoid a
    // zip-lib dependency. Extracts to a temp dir, then we move
    // ``uv.exe`` into place.
    const extractDir = await fs.promises.mkdtemp(path.join(os.tmpdir(), "uv-zip-"));
    try {
      await runProcess(
        "powershell.exe",
        ["-NoProfile", "-Command", `Expand-Archive -Path '${archive}' -DestinationPath '${extractDir}' -Force`],
      );
      const found = await findFileNamed(extractDir, "uv.exe");
      if (!found) throw new Error("uv.exe not found in archive");
      await fs.promises.rename(found, dest);
    } finally {
      await fs.promises.rm(extractDir, { recursive: true, force: true });
    }
  } else {
    // tar.gz on macOS/Linux. ``tar`` is universally available.
    const extractDir = await fs.promises.mkdtemp(path.join(os.tmpdir(), "uv-tar-"));
    try {
      await runProcess("tar", ["xzf", archive, "-C", extractDir]);
      const found = await findFileNamed(extractDir, "uv");
      if (!found) throw new Error("uv binary not found in archive");
      await fs.promises.rename(found, dest);
      await fs.promises.chmod(dest, 0o755);
    } finally {
      await fs.promises.rm(extractDir, { recursive: true, force: true });
    }
  }
}

async function findFileNamed(root: string, name: string): Promise<string | null> {
  const entries = await fs.promises.readdir(root, { withFileTypes: true });
  for (const e of entries) {
    const full = path.join(root, e.name);
    if (e.isFile() && e.name === name) return full;
    if (e.isDirectory()) {
      const nested = await findFileNamed(full, name);
      if (nested) return nested;
    }
  }
  return null;
}

// ── uv / process invocation ────────────────────────────────────────

function runUv(uvPath: string, args: string[]): Promise<void> {
  return runProcess(uvPath, args, { timeoutMs: 10 * 60_000 });
}

function runProcess(
  cmd: string,
  args: string[],
  opts: { timeoutMs?: number; env?: Record<string, string> } = {},
): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, {
      stdio: ["ignore", "pipe", "pipe"],
      env: opts.env ? { ...process.env, ...opts.env } : process.env,
    });
    let stderr = "";
    child.stdout?.on("data", () => {}); // drain
    child.stderr?.on("data", (b) => {
      stderr = (stderr + b.toString()).slice(-4096);
    });
    const timer = opts.timeoutMs
      ? setTimeout(() => {
          child.kill("SIGKILL");
          reject(new Error(`${cmd} ${args.join(" ")} timed out`));
        }, opts.timeoutMs)
      : null;
    child.on("error", (e) => {
      if (timer) clearTimeout(timer);
      reject(e);
    });
    child.on("exit", (code) => {
      if (timer) clearTimeout(timer);
      if (code === 0) resolve();
      else reject(new Error(`${cmd} exited ${code}: ${stderr.trim()}`));
    });
  });
}

// ── Filesystem helpers ─────────────────────────────────────────────

async function pathExists(p: string): Promise<boolean> {
  try {
    await fs.promises.stat(p);
    return true;
  } catch {
    return false;
  }
}

async function isExecutable(p: string): Promise<boolean> {
  try {
    const st = await fs.promises.stat(p);
    return st.isFile();
  } catch {
    return false;
  }
}

async function readFileOrNull(p: string): Promise<string | null> {
  try {
    return await fs.promises.readFile(p, "utf8");
  } catch {
    return null;
  }
}


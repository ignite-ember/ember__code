package sh.igniteember.embercode

import com.intellij.openapi.diagnostic.thisLogger
import java.io.File
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.time.Duration

/**
 * Owns the lifecycle of the *managed* Ember backend installation.
 *
 * The plugin's goal is "zero-touch": the user installs the plugin
 * and the chat panel works — no `pip install`, no `EMBER_PYTHON`,
 * no virtualenv juggling. To get there we ship nothing about Python
 * in the plugin itself, but on first launch we:
 *
 *   1. Download the ``uv`` binary for the current OS/arch (Astral's
 *      Rust-based Python package manager — single static binary,
 *      ~25 MB, handles Python install + venv + pip).
 *   2. Use ``uv python install`` to fetch a pinned CPython.
 *   3. Use ``uv venv`` to create the backend venv.
 *   4. Use ``uv pip install ignite-ember==<pinned>`` to install the
 *      backend code itself.
 *
 * Everything lives under ``~/.cache/ember-code/`` (or the OS cache
 * dir on Windows). Subsequent launches reuse the cache directly and
 * skip every step above — startup overhead drops to ``uv``'s venv
 * lookup, which is sub-50 ms.
 *
 * **Development override.** If ``EMBER_DEV_BACKEND`` is set, we
 * return that path verbatim and skip the bootstrap entirely. Used
 * during local plugin development to point at an editable install
 * of ``ignite-ember`` (`pip install -e .` in the source tree). Not
 * exposed in the UI; the plugin doesn't have a settings page on
 * purpose.
 */
object EmberRuntime {
    private val log = thisLogger()

    /** Pinned CPython tag fed to ``uv python install``. */
    private const val PYTHON_VERSION = "3.12"

    /** Pinned ``uv`` release used for the runtime bootstrap. Bumped
     *  when we need a new uv feature; otherwise stable. */
    private const val UV_VERSION = "0.5.7"

    /** Pinned ``ignite-ember`` version installed into the managed
     *  venv — read at runtime from the resource ``build.gradle.kts``
     *  generates out of ``pyproject.toml``. Single source of truth
     *  for the version across the Python package + plugin so a
     *  release tag bump flows automatically into the next plugin
     *  build. */
    private val IGNITE_EMBER_VERSION: String by lazy {
        val props = java.util.Properties()
        EmberRuntime::class.java.classLoader
            .getResourceAsStream("META-INF/ember-version.properties")
            ?.use { props.load(it) }
        props.getProperty("ignite-ember-version")
            ?: error("ember-version.properties missing — gradle generateEmberVersion task didn't run")
    }

    /** Marker file that records what's currently installed under the
     *  managed venv. If any of these fields drift from the constants
     *  above we tear the venv down and rebuild — that's the upgrade
     *  path on plugin updates. */
    private const val INSTALL_MARKER = "ember-install.json"

    /** Result of [ensureBackendPython]: the Python interpreter to
     *  spawn the BE with, plus environment variables the caller
     *  should layer onto the BE process. ``HF_HOME`` keeps the
     *  HuggingFace cache inside the plugin-managed directory so
     *  "Reinstall Backend (Clean)" really wipes everything (instead
     *  of leaving ~250 MB of cached embeddings in
     *  ``~/.cache/huggingface``). */
    data class BackendInstall(val python: Path, val env: Map<String, String>)

    /**
     * Resolve a Python interpreter with ``ignite-ember`` installed
     * AND the sentence-transformer embedding model pre-warmed.
     * Bootstraps on first call; returns from cache thereafter. The
     * ``listener`` receives short human-readable status strings so
     * the tool window can show "Downloading uv…" / "Installing
     * Python…" / "Installing backend…" / "Downloading embedding
     * model…" while the user waits.
     *
     * Blocks the calling thread. Caller should run this on a
     * background thread (``EmberBackendService`` does).
     */
    fun ensureBackendPython(listener: (String) -> Unit): BackendInstall {
        // ── Dev override ──
        System.getenv("EMBER_DEV_BACKEND")?.takeIf { it.isNotBlank() }?.let { dev ->
            log.info("EMBER_DEV_BACKEND set; bypassing managed venv: $dev")
            // No HF_HOME override in dev mode — devs use their normal
            // ``~/.cache/huggingface`` so the model isn't re-downloaded
            // per ember-code checkout.
            return BackendInstall(Path.of(dev), emptyMap())
        }

        val cache = cacheRoot()
        Files.createDirectories(cache)
        val hfHome = cache.resolve("huggingface")

        val markerPath = cache.resolve(INSTALL_MARKER)
        val currentMarker =
            "uv=$UV_VERSION;python=$PYTHON_VERSION;ignite=$IGNITE_EMBER_VERSION"
        val previousMarker = runCatching { Files.readString(markerPath).trim() }.getOrNull()

        // ── Step 1: uv binary ──
        val uv = cache.resolve(uvBinName())
        if (!Files.isExecutable(uv) || previousMarker != currentMarker) {
            listener("Downloading uv (one-time, ~25 MB)…")
            downloadUv(uv)
        }

        val venv = cache.resolve("venv")
        val venvPython = venv.resolve(venvPythonRelPath())

        // ── Steps 2-4: pinned Python + venv + ignite-ember ──
        if (!Files.isExecutable(venvPython) || previousMarker != currentMarker) {
            // Old venv lingering from a previous plugin version — drop
            // it before re-creating so we don't mix wheels.
            if (Files.exists(venv)) {
                listener("Refreshing managed venv…")
                deleteRecursively(venv)
            }

            listener("Installing Python $PYTHON_VERSION (one-time)…")
            runUv(uv, listOf("python", "install", PYTHON_VERSION))

            listener("Creating backend venv…")
            runUv(uv, listOf("venv", "--python", PYTHON_VERSION, venv.toString()))

            listener("Installing ignite-ember (one-time)…")
            runUv(
                uv,
                listOf(
                    "pip",
                    "install",
                    "--python",
                    venvPython.toString(),
                    "ignite-ember==$IGNITE_EMBER_VERSION",
                ),
            )

            // Pre-warm the sentence-transformer embedding cache so
            // the user's first agent run doesn't stall mid-chat on
            // a silent 90 MB HuggingFace download. ``HF_HOME``
            // points at the managed cache so a clean reinstall
            // catches it too.
            listener("Downloading embedding model (one-time, ~90 MB)…")
            runProcess(
                venvPython,
                listOf("-m", "ember_code.prefetch_models"),
                env = mapOf("HF_HOME" to hfHome.toString()),
            )

            Files.writeString(markerPath, currentMarker)
        }

        return BackendInstall(
            python = venvPython,
            env = mapOf("HF_HOME" to hfHome.toString()),
        )
    }

    // ── Platform + paths ──

    /** ``~/.cache/ember-code`` on macOS/Linux, ``%LOCALAPPDATA%/ember-code``
     *  on Windows. Picks a stable per-user location that survives
     *  plugin reinstalls. */
    private fun cacheRoot(): Path {
        val os = System.getProperty("os.name").lowercase()
        val home = System.getProperty("user.home")
        return when {
            os.contains("win") -> {
                val local = System.getenv("LOCALAPPDATA") ?: "$home\\AppData\\Local"
                Path.of(local, "ember-code")
            }
            os.contains("mac") -> Path.of(home, "Library", "Caches", "ember-code")
            else -> {
                val xdg = System.getenv("XDG_CACHE_HOME")
                if (xdg.isNullOrBlank()) Path.of(home, ".cache", "ember-code")
                else Path.of(xdg, "ember-code")
            }
        }
    }

    private fun uvBinName(): String =
        if (System.getProperty("os.name").lowercase().contains("win")) "uv.exe" else "uv"

    private fun venvPythonRelPath(): String =
        if (System.getProperty("os.name").lowercase().contains("win")) "Scripts/python.exe"
        else "bin/python"

    /** Map the running JVM's OS+arch onto the GitHub release asset
     *  name uv ships. We deliberately fail loud for anything off the
     *  beaten path so silent fallbacks don't leave a half-bootstrapped
     *  cache lying around. */
    private fun uvTarget(): String {
        val os = System.getProperty("os.name").lowercase()
        val arch = System.getProperty("os.arch").lowercase()
        return when {
            os.contains("mac") && (arch == "aarch64" || arch == "arm64") ->
                "aarch64-apple-darwin"
            os.contains("mac") && (arch == "x86_64" || arch == "amd64") ->
                "x86_64-apple-darwin"
            os.contains("win") -> "x86_64-pc-windows-msvc"
            os.contains("nix") || os.contains("nux") -> when (arch) {
                "aarch64", "arm64" -> "aarch64-unknown-linux-gnu"
                else -> "x86_64-unknown-linux-gnu"
            }
            else -> error("Unsupported platform: os=$os arch=$arch")
        }
    }

    // ── Downloads ──

    private fun downloadUv(target: Path) {
        val ext = if (System.getProperty("os.name").lowercase().contains("win")) "zip" else "tar.gz"
        val triple = uvTarget()
        val url = "https://github.com/astral-sh/uv/releases/download/" +
            "$UV_VERSION/uv-$triple.$ext"
        log.info("Downloading uv from $url")

        val tmp = Files.createTempFile("uv-download-", ".$ext")
        try {
            val client = HttpClient.newBuilder()
                .followRedirects(HttpClient.Redirect.ALWAYS)
                .connectTimeout(Duration.ofSeconds(15))
                .build()
            val req = HttpRequest.newBuilder(URI.create(url))
                .timeout(Duration.ofMinutes(2))
                .GET()
                .build()
            val rsp = client.send(req, HttpResponse.BodyHandlers.ofFile(tmp))
            if (rsp.statusCode() !in 200..299) {
                error("uv download failed: HTTP ${rsp.statusCode()} from $url")
            }
            extractUv(tmp, target, ext)
        } finally {
            runCatching { Files.deleteIfExists(tmp) }
        }
    }

    private fun extractUv(archive: Path, dest: Path, ext: String) {
        Files.createDirectories(dest.parent)
        val parentDir = dest.parent
        if (ext == "zip") {
            // The Windows zip contains uv.exe at the top level.
            java.util.zip.ZipInputStream(Files.newInputStream(archive)).use { zin ->
                var entry = zin.nextEntry
                while (entry != null) {
                    if (!entry.isDirectory && entry.name.endsWith("uv.exe")) {
                        Files.copy(zin, dest, StandardCopyOption.REPLACE_EXISTING)
                        return
                    }
                    entry = zin.nextEntry
                }
            }
            error("uv binary not found in archive $archive")
        } else {
            // tar.gz on Unix. Use the system tar — JDK has no built-in.
            // Extract into the parent of ``dest`` and look for the
            // single ``uv`` file inside ``uv-<triple>/uv``.
            val extractDir = Files.createTempDirectory(parentDir, "uv-extract-")
            try {
                val proc = ProcessBuilder("tar", "xzf", archive.toString(), "-C", extractDir.toString())
                    .redirectErrorStream(true)
                    .start()
                if (!proc.waitFor(60, java.util.concurrent.TimeUnit.SECONDS)) {
                    proc.destroyForcibly()
                    error("tar extraction of uv timed out")
                }
                if (proc.exitValue() != 0) {
                    error("tar extraction of uv failed (exit ${proc.exitValue()})")
                }
                // Find uv inside the extracted tree.
                val found = Files.walk(extractDir).use { stream ->
                    stream.filter { it.fileName.toString() == "uv" && Files.isRegularFile(it) }
                        .findFirst().orElse(null)
                } ?: error("uv binary missing from extracted archive")
                Files.move(found, dest, StandardCopyOption.REPLACE_EXISTING)
                dest.toFile().setExecutable(true, false)
            } finally {
                runCatching { deleteRecursively(extractDir) }
            }
        }
    }

    // ── Subprocess invocation ──

    private fun runUv(uv: Path, args: List<String>) {
        runProcess(uv, args)
    }

    /** Run a subprocess with our managed environment layer. Used for
     *  ``uv`` invocations and for the post-install model prefetch,
     *  both of which need the same log-and-fail-loud behaviour. */
    private fun runProcess(
        bin: Path,
        args: List<String>,
        env: Map<String, String> = emptyMap(),
    ) {
        val cmd = listOf(bin.toString()) + args
        log.info("Running: ${cmd.joinToString(" ")}")
        val builder = ProcessBuilder(cmd).redirectErrorStream(true)
        if (env.isNotEmpty()) builder.environment().putAll(env)
        val proc = builder.start()
        val output = StringBuilder()
        Thread {
            proc.inputStream.bufferedReader().use { reader ->
                reader.forEachLine { line ->
                    synchronized(output) {
                        output.append(line).append('\n')
                        if (output.length > 8192) output.delete(0, output.length - 8192)
                    }
                    log.debug("subprocess: $line")
                }
            }
        }.apply { isDaemon = true; start() }

        if (!proc.waitFor(10, java.util.concurrent.TimeUnit.MINUTES)) {
            proc.destroyForcibly()
            error("Command timed out: ${bin.fileName} ${args.joinToString(" ")}")
        }
        if (proc.exitValue() != 0) {
            val tail = synchronized(output) { output.toString().trim() }
            error("Command failed (exit ${proc.exitValue()}): ${bin.fileName} ${args.joinToString(" ")}\n$tail")
        }
    }

    // ── Utilities ──

    private fun deleteRecursively(path: Path) {
        if (!Files.exists(path)) return
        Files.walk(path).use { stream ->
            stream.sorted(Comparator.reverseOrder())
                .forEach { p -> runCatching { Files.delete(p) } }
        }
    }

    /** Wipe the entire managed cache and force a re-bootstrap on the
     *  next ``ensureBackendPython`` call. Used by the "Restart
     *  backend (clean install)" action so users can recover from a
     *  corrupted venv without leaving the IDE. */
    fun resetCache() {
        val root = cacheRoot()
        if (Files.exists(root)) {
            log.info("Wiping Ember managed cache: $root")
            deleteRecursively(root)
        }
    }
}

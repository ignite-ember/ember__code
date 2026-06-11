package sh.igniteember.embercode

import com.intellij.openapi.Disposable
import com.intellij.openapi.components.Service
import com.intellij.openapi.diagnostic.thisLogger
import com.intellij.openapi.project.Project
import java.io.BufferedReader
import java.io.InputStreamReader
import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit

/**
 * Project-level service owning the Ember backend process.
 *
 * Spawns `python -m ember_code.backend --ws-port 0 --project-dir <root>`
 * and parses the JSON ready line for the bound WebSocket port. The
 * process is killed when the project closes (Disposable), and also
 * self-terminates if the IDE dies (EMBER_PARENT_PID watchdog).
 */
@Service(Service.Level.PROJECT)
class EmberBackendService(private val project: Project) : Disposable {

    private val log = thisLogger()
    private var process: Process? = null

    @Volatile
    var wsPort: Int? = null
        private set

    /** Start the backend (idempotent); resolves with the WS port. */
    fun ensureStarted(): CompletableFuture<Int> {
        wsPort?.let { return CompletableFuture.completedFuture(it) }
        val future = CompletableFuture<Int>()
        val python = System.getenv("EMBER_PYTHON") ?: "python3"
        val projectDir = project.basePath ?: "."

        Thread {
            try {
                val proc = ProcessBuilder(
                    python, "-m", "ember_code.backend",
                    "--ws-port", "0",
                    "--project-dir", projectDir,
                ).apply {
                    environment()["EMBER_PARENT_PID"] = ProcessHandle.current().pid().toString()
                    redirectErrorStream(false)
                }.start()
                process = proc

                val reader = BufferedReader(InputStreamReader(proc.inputStream))
                var line: String?
                while (reader.readLine().also { line = it } != null) {
                    val l = line!!.trim()
                    // Ready line: {"status": "ready", "ws_port": N, ...}
                    if (l.startsWith("{") && l.contains("\"ready\"")) {
                        val match = Regex("\"ws_port\"\\s*:\\s*(\\d+)").find(l)
                        val port = match?.groupValues?.get(1)?.toIntOrNull()
                        if (port != null) {
                            wsPort = port
                            future.complete(port)
                            // Keep draining stdout so the BE never blocks.
                            while (reader.readLine() != null) { /* drain */ }
                            return@Thread
                        }
                    }
                }
                future.completeExceptionally(IllegalStateException("backend exited before ready"))
            } catch (e: Exception) {
                log.warn("Ember backend failed to start", e)
                future.completeExceptionally(e)
            }
        }.apply {
            isDaemon = true
            name = "ember-backend-launcher"
        }.start()

        return future
    }

    override fun dispose() {
        process?.let { proc ->
            proc.destroy()
            if (!proc.waitFor(5, TimeUnit.SECONDS)) {
                proc.destroyForcibly()
            }
        }
        process = null
        wsPort = null
    }
}

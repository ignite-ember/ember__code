package sh.igniteember.embercode

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.service
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.ui.jcef.JBCefBrowser
import com.intellij.ui.components.JBLabel
import com.intellij.util.ui.JBUI
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import javax.swing.JPanel
import java.awt.BorderLayout

/**
 * "Ember Code" tool window — a JCEF browser hosting the shared web UI
 * (clients/web, bundled under /webui in plugin resources), connected
 * to the project's backend via `?ws=` query param.
 */
class EmberToolWindowFactory : ToolWindowFactory {

    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val panel = JPanel(BorderLayout())
        panel.add(JBLabel("Starting Ember backend…", JBLabel.CENTER).apply {
            border = JBUI.Borders.empty(24)
        }, BorderLayout.CENTER)
        val content = toolWindow.contentManager.factory.createContent(panel, "", false)
        toolWindow.contentManager.addContent(content)

        val backend = project.service<EmberBackendService>()
        backend.ensureStarted().whenComplete { port, err ->
            ApplicationManager.getApplication().invokeLater {
                panel.removeAll()
                if (err != null || port == null) {
                    panel.add(
                        JBLabel(
                            "<html>Ember backend failed to start: ${err?.message}<br>" +
                                "Install with: pip install ignite-ember — or set EMBER_PYTHON.</html>",
                            JBLabel.CENTER,
                        ),
                        BorderLayout.CENTER,
                    )
                } else {
                    val indexUrl = extractWebUi()
                    val browser = JBCefBrowser("$indexUrl?ws=ws%3A%2F%2F127.0.0.1%3A$port")
                    panel.add(browser.component, BorderLayout.CENTER)
                }
                panel.revalidate()
                panel.repaint()
            }
        }
    }

    /**
     * Extract the bundled web UI from plugin resources to a temp dir
     * so JCEF can load it from file://. Re-extracted per IDE session —
     * cheap (3 small files) and avoids stale-cache issues on upgrade.
     */
    private fun extractWebUi(): String {
        val dir = Files.createTempDirectory("ember-webui")
        val cl = javaClass.classLoader
        // Vite emits index.html + hashed assets; walk the manifest-less
        // bundle by extracting the known root and the assets dir listing.
        for (name in listOf("webui/index.html")) {
            cl.getResourceAsStream(name)?.use { input ->
                val target = dir.resolve(name.removePrefix("webui/"))
                Files.createDirectories(target.parent ?: dir)
                Files.copy(input, target, StandardCopyOption.REPLACE_EXISTING)
            }
        }
        // Assets: enumerate via the index.html references.
        val index = dir.resolve("index.html")
        if (Files.exists(index)) {
            val html = Files.readString(index)
            Regex("\\./(assets/[A-Za-z0-9._-]+)").findAll(html).forEach { m ->
                val rel = m.groupValues[1]
                cl.getResourceAsStream("webui/$rel")?.use { input ->
                    val target = dir.resolve(rel)
                    Files.createDirectories(target.parent)
                    Files.copy(input, target, StandardCopyOption.REPLACE_EXISTING)
                }
            }
        }
        return index.toUri().toString()
    }
}

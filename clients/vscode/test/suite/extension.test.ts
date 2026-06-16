/**
 * Smoke tests for the Ember Code VSCode extension.
 *
 * These run inside the extension host process (via
 * ``@vscode/test-electron``) and assert on the IDE-side surface:
 * activation, command registration, panel mount. Webview DOM is
 * covered by the web e2e suite — the webview is a sandboxed iframe
 * the extension host can't introspect.
 *
 * The real BE bootstrap (uv → Python → ignite-ember, ~30 s) is
 * bypassed by pointing ``emberCode.pythonPath`` at a fake Node
 * script that just prints the ready JSON. The fake doesn't expose
 * a WS port, so the webview falls back to "Connecting…" — fine
 * for these tests.
 */

import * as assert from "assert";
import * as path from "path";
import * as vscode from "vscode";

const PUBLISHER_ID = "ignite-ember.ember-code-vscode";

suite("Ember Code extension", () => {
  suiteSetup(async () => {
    // Anchor the fake "Python" path on the extension's install
    // directory (the source tree, not the compiled-output mirror)
    // so we don't have to copy fake-backend.js into ``out/``.
    const ext = vscode.extensions.getExtension(PUBLISHER_ID);
    assert.ok(ext, `extension ${PUBLISHER_ID} not found in test host`);
    const fakeBe = path.join(ext!.extensionPath, "test", "fake-backend.js");
    await vscode.workspace
      .getConfiguration("emberCode")
      .update("pythonPath", fakeBe, vscode.ConfigurationTarget.Global);
  });

  suiteTeardown(async () => {
    await vscode.workspace
      .getConfiguration("emberCode")
      .update("pythonPath", undefined, vscode.ConfigurationTarget.Global);
  });

  test("extension is present and can be activated", async () => {
    const ext = vscode.extensions.getExtension(PUBLISHER_ID);
    assert.ok(ext, `extension ${PUBLISHER_ID} not found`);
    await ext!.activate();
    assert.ok(ext!.isActive, "extension failed to activate");
  });

  test("all contributed commands are registered", async () => {
    const ext = vscode.extensions.getExtension(PUBLISHER_ID);
    await ext!.activate();
    const all = await vscode.commands.getCommands(true);
    const expected = [
      "emberCode.open",
      "emberCode.addSelectionToChat",
      "emberCode.addFileToChat",
      "emberCode.restart",
      "emberCode.reinstall",
    ];
    for (const cmd of expected) {
      assert.ok(
        all.includes(cmd),
        `command ${cmd} not registered (registered: ${all.filter((c) => c.startsWith("emberCode")).join(", ")})`,
      );
    }
  });

  test("emberCode.open creates the chat panel", async () => {
    const ext = vscode.extensions.getExtension(PUBLISHER_ID);
    await ext!.activate();

    // Capture error notifications so we can include them in the
    // assertion message — extension swallows BE-spawn failures into
    // ``showErrorMessage`` and returns early without a panel; that
    // would otherwise look like a silent test failure.
    const errors: string[] = [];
    const orig = vscode.window.showErrorMessage;
    (vscode.window as any).showErrorMessage = (msg: string) => {
      errors.push(msg);
      // Don't forward — the modal would block the test. We only
      // need the message text for diagnostics.
      return Promise.resolve(undefined);
    };

    try {
      await vscode.commands.executeCommand("emberCode.open");

      // Poll for the tab to land in the tab-groups model.
      const deadline = Date.now() + 5_000;
      let emberTab: vscode.Tab | undefined;
      while (Date.now() < deadline) {
        emberTab = vscode.window.tabGroups.all
          .flatMap((g) => g.tabs)
          .find((t) => t.label === "Ember Code");
        if (emberTab) break;
        await new Promise((r) => setTimeout(r, 100));
      }
      assert.ok(
        emberTab,
        `Ember Code panel tab not found within 5 s. Errors: ${errors.join(" | ") || "(none)"}`,
      );
    } finally {
      (vscode.window as any).showErrorMessage = orig;
    }
  });

  test("addSelectionToChat is a no-op when no editor is active", async () => {
    // The command should not crash when invoked without an active
    // text editor. It just returns silently. We don't have a way to
    // open a text editor easily in this minimal test harness, so we
    // assert the no-active-editor branch is clean.
    await vscode.commands.executeCommand("emberCode.addSelectionToChat");
    // If we get here without throwing, the test passes.
    assert.ok(true);
  });

  test("addFileToChat tolerates missing arguments", async () => {
    // The command is wired to the explorer/context menu, which
    // passes a Uri. When invoked from the command palette (no args),
    // it should bail out cleanly.
    await vscode.commands.executeCommand("emberCode.addFileToChat");
    assert.ok(true);
  });
});

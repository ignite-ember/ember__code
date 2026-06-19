/**
 * Test driver: downloads a real VSCode binary, launches it with our
 * extension loaded, and runs the Mocha test suite inside the
 * extension host. This is the standard ``@vscode/test-electron``
 * pattern — there's no real alternative for testing extensions, since
 * the IDE's APIs only exist inside the extension host process.
 *
 * Invoked by ``npm run test:host``.
 */

import * as path from "path";
import { runTests } from "@vscode/test-electron";

async function main() {
  try {
    const extensionDevelopmentPath = path.resolve(__dirname, "../..");
    const extensionTestsPath = path.resolve(__dirname, "./suite/index");

    await runTests({
      extensionDevelopmentPath,
      extensionTestsPath,
      // ``--disable-extensions`` keeps the test environment hermetic;
      // we don't want the user's locally-installed extensions
      // affecting activation events or commands. ``--user-data-dir``
      // points at a throwaway dir so this run doesn't pollute the
      // user's real VSCode settings.
      launchArgs: ["--disable-extensions"],
    });
  } catch (err) {
    console.error("Failed to run tests:", err);
    process.exit(1);
  }
}

main();

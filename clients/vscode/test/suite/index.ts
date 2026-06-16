/**
 * Mocha bootstrap that runs inside the extension host. Discovers
 * every ``*.test.js`` under ``suite/`` and adds it to a single
 * Mocha runner. Returns a Promise that resolves with the number of
 * failures so the driver can exit with the right code.
 */

import * as path from "path";
import Mocha from "mocha";
import { glob } from "glob";

export async function run(): Promise<void> {
  const mocha = new Mocha({
    ui: "tdd",
    color: true,
    timeout: 60_000, // extension activation + command dispatch can be slow
  });

  const testsRoot = path.resolve(__dirname, ".");
  const files = await glob("**/*.test.js", { cwd: testsRoot });
  for (const f of files) mocha.addFile(path.resolve(testsRoot, f));

  return new Promise<void>((resolve, reject) => {
    try {
      mocha.run((failures: number) => {
        if (failures > 0) reject(new Error(`${failures} test(s) failed`));
        else resolve();
      });
    } catch (err) {
      reject(err);
    }
  });
}

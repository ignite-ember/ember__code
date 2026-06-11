# Ember Code — JetBrains plugin

Tool window (right anchor) hosting the shared web UI (`clients/web`)
in a JCEF browser, backed by a per-project Ember backend process over
a loopback WebSocket.

## Build

Requires JDK 17+ (Gradle wrapper fetches Gradle itself):

```bash
cd clients/web && npm install && npm run build
cd ../jetbrains
gradle buildPlugin     # or: gradle runIde for a sandbox IDE
```

The plugin zip lands in `build/distributions/`.

Set `EMBER_PYTHON` if `ignite-ember` lives in a venv.

> NOTE: not compiled in CI yet — requires a JDK, which this dev machine
> doesn't have. The web UI and backend protocol are covered by tests;
> the Kotlin shell is spawn/JCEF glue.

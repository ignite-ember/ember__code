@echo off
:: Windows wrapper around ``fake-backend.js`` so the extension's
:: ``spawn(emberCode.pythonPath, ...)`` works on Windows. Shebang
:: lines (``#!/usr/bin/env node``) don't apply on Windows; without
:: this wrapper, ``spawn`` rejects the bare .js with ``EFTYPE``.
::
:: ``%~dp0`` expands to the directory this .cmd lives in, so the
:: wrapper finds its sibling JS regardless of cwd. ``%*`` forwards
:: every argument the extension passes (``-m ember_code.backend
:: --ws-port 0 --project-dir <dir>`` etc.) — the fake-backend
:: ignores them and just prints its ready envelope.
node "%~dp0fake-backend.js" %*

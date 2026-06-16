/**
 * ThemeToggle — single button that cycles `auto → light → dark → auto`.
 *
 * State lives on `<html data-theme="…">` and mirrored to localStorage
 * so it survives reloads. In `auto`, we mirror the OS preference into
 * `data-os-prefers-light`, so the same CSS picks the right palette
 * without needing the @media rule to fight an explicit override.
 */

import { useEffect, useState } from "react";

export type Theme = "auto" | "light" | "dark";

const STORAGE_KEY = "ember:theme";

function readStored(): Theme {
  if (typeof window === "undefined") return "auto";
  const v = window.localStorage?.getItem(STORAGE_KEY);
  return v === "light" || v === "dark" || v === "auto" ? v : "auto";
}

function applyTheme(theme: Theme) {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = theme;
  if (theme === "auto") {
    const prefersLight = window.matchMedia?.("(prefers-color-scheme: light)").matches;
    document.documentElement.dataset.osPrefersLight = prefersLight ? "1" : "0";
  } else {
    delete document.documentElement.dataset.osPrefersLight;
  }
}

// Apply the stored theme immediately on import so the very first
// React paint already has the right palette — no flash.
if (typeof document !== "undefined") applyTheme(readStored());

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readStored);

  useEffect(() => {
    applyTheme(theme);
    try {
      window.localStorage?.setItem(STORAGE_KEY, theme);
    } catch {
      // localStorage blocked (private mode etc.) — ignore.
    }
  }, [theme]);

  // When in auto, follow the OS as it changes (system flips dark/light).
  useEffect(() => {
    if (theme !== "auto") return;
    const mq = window.matchMedia?.("(prefers-color-scheme: light)");
    if (!mq) return;
    const onChange = () => applyTheme("auto");
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, [theme]);

  const next: Theme = theme === "auto" ? "light" : theme === "light" ? "dark" : "auto";
  const label =
    theme === "auto"
      ? "Theme: auto · click for light"
      : theme === "light"
        ? "Theme: light · click for dark"
        : "Theme: dark · click for auto";

  return (
    <button
      className="theme-toggle"
      type="button"
      title={label}
      aria-label={label}
      onClick={() => setTheme(next)}
    >
      {theme === "light" ? <SunIcon /> : theme === "dark" ? <MoonIcon /> : <AutoIcon />}
    </button>
  );
}

function SunIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="3" stroke="currentColor" strokeWidth="1.4" />
      <path
        d="M8 1.5v1.6M8 12.9v1.6M1.5 8h1.6M12.9 8h1.6M3.3 3.3l1.1 1.1M11.6 11.6l1.1 1.1M3.3 12.7l1.1-1.1M11.6 4.4l1.1-1.1"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" aria-hidden="true">
      <path
        d="M13.2 9.4A5.4 5.4 0 0 1 6.6 2.8c0-.32.03-.63.08-.94A6 6 0 1 0 14.14 9.32c-.31.05-.62.08-.94.08z"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function AutoIcon() {
  return (
    // Half-sun / half-moon: a circle split down the middle, sun-side
    // is filled outline + rays, moon-side is solid (the dark half).
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="4.2" stroke="currentColor" strokeWidth="1.3" />
      <path d="M8 3.8a4.2 4.2 0 0 0 0 8.4z" fill="currentColor" />
      <path
        d="M8 1.2v1.2M8 13.6v1.2M1.2 8h1.2M13.6 8h1.2"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
      />
    </svg>
  );
}

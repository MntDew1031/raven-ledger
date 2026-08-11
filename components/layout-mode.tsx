"use client";

import { Monitor, Smartphone } from "lucide-react";
import { useEffect, useState } from "react";

export type LayoutMode = "auto" | "desktop";

const STORAGE_KEY = "raven-layout-mode";
// viewport-fit=cover must be preserved here too, or returning to this mode
// would quietly re-break the safe-area padding on the tab bar.
const AUTO_VIEWPORT = "width=device-width, initial-scale=1, viewport-fit=cover";
// Wide enough for the full desktop grid to lay out honestly. The phone then
// zooms it, exactly as a browser's own "Request desktop site" does.
const DESKTOP_VIEWPORT = "width=1280, viewport-fit=cover";

export function readLayoutMode(): LayoutMode {
  if (typeof window === "undefined") return "auto";
  return window.localStorage.getItem(STORAGE_KEY) === "desktop"
    ? "desktop"
    : "auto";
}

/**
 * Force the desktop layout on a phone.
 *
 * This is a per-device choice, so it lives in `localStorage` rather than the
 * profile: wanting the wide table on your phone says nothing about what you
 * want on a laptop, and syncing it would fight you on whichever device you
 * chose second.
 *
 * The mechanism is the viewport meta tag rather than CSS. Every breakpoint in
 * the app keys off viewport width, so telling the browser the viewport is
 * 1280px wide makes all of them agree at once — no parallel set of rules to
 * keep in step, which is exactly the kind of drift that already broke the
 * transaction rows once.
 */
export function applyLayoutMode(mode: LayoutMode): void {
  const meta = document.querySelector('meta[name="viewport"]');
  if (!meta) return;
  meta.setAttribute(
    "content",
    mode === "desktop" ? DESKTOP_VIEWPORT : AUTO_VIEWPORT,
  );
  document.documentElement.dataset.layoutMode = mode;
}

export function LayoutModeToggle({ compact = false }: { compact?: boolean }) {
  // Read the stored choice during initialization rather than in an effect.
  // Server-side there is no localStorage, so both sides start at "auto" and
  // hydration matches; the effect below only has to apply it to the document.
  const [mode, setMode] = useState<LayoutMode>(readLayoutMode);

  useEffect(() => {
    applyLayoutMode(mode);
  }, [mode]);

  function choose(next: LayoutMode) {
    setMode(next);
    window.localStorage.setItem(STORAGE_KEY, next);
    applyLayoutMode(next);
  }

  return (
    <div
      aria-label="Layout"
      className={`layout-mode${compact ? " compact" : ""}`}
      role="group"
    >
      <button
        aria-pressed={mode === "auto"}
        className={mode === "auto" ? "active" : ""}
        onClick={() => choose("auto")}
        type="button"
      >
        <Smartphone size={13} /> Fits my screen
      </button>
      <button
        aria-pressed={mode === "desktop"}
        className={mode === "desktop" ? "active" : ""}
        onClick={() => choose("desktop")}
        type="button"
      >
        <Monitor size={13} /> Full desktop
      </button>
    </div>
  );
}

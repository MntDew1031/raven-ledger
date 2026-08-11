"use client";

import { ChevronDown } from "lucide-react";
import { ReactNode, useCallback, useSyncExternalStore } from "react";

/**
 * A section of the Budget page that can be folded away.
 *
 * Alex asked for this after seeing the page on his phone: the plan itself is
 * what he goes there for, and the paycheque explanation, the earners and the
 * goals sit between him and it. Folding is per-person and per-device, kept in
 * `localStorage` rather than on the server — it is a view preference about one
 * screen, not a fact about the household, and syncing it would mean collapsing
 * a section on a phone hid it on a laptop.
 *
 * **The summary stays visible when it is closed.** A collapsed section that
 * says only "Who earns what" has to be opened to learn anything from; one that
 * says "$6,860.92 this month" has already answered the question.
 *
 * Read through `useSyncExternalStore` rather than an effect, because that is
 * what it is: an external store with a value the server cannot know. The
 * server snapshot is the default, so the first paint matches the markup and
 * hydration does not throw it away.
 */

const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function read(storageKey: string): string | null {
  try {
    return window.localStorage.getItem(`raven-section-${storageKey}`);
  } catch {
    // A browser refusing storage is not a reason to hide a section.
    return null;
  }
}

function write(storageKey: string, open: boolean) {
  try {
    window.localStorage.setItem(
      `raven-section-${storageKey}`,
      open ? "open" : "closed",
    );
  } catch {
    /* nothing to do */
  }
  for (const listener of listeners) listener();
}

export function CollapsibleSection({
  storageKey,
  title,
  summary,
  defaultOpen = true,
  children,
}: {
  storageKey: string;
  title: string;
  summary?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const open = useSyncExternalStore(
    subscribe,
    useCallback(() => {
      const stored = read(storageKey);
      return stored === null ? defaultOpen : stored === "open";
    }, [storageKey, defaultOpen]),
    useCallback(() => defaultOpen, [defaultOpen]),
  );

  return (
    <section className={`collapsible-section ${open ? "open" : "closed"}`}>
      <button
        aria-expanded={open}
        className="collapsible-header"
        onClick={() => write(storageKey, !open)}
        type="button"
      >
        <span className="collapsible-title">{title}</span>
        {summary != null && (
          <span className="collapsible-summary">{summary}</span>
        )}
        <ChevronDown aria-hidden className="collapsible-chevron" size={17} />
      </button>
      {/* Unmounted rather than hidden: each of these sections fetches, and a
          folded one should cost nothing. */}
      {open && <div className="collapsible-body">{children}</div>}
    </section>
  );
}

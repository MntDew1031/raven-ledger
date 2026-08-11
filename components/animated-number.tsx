"use client";

import { useEffect, useRef, useState } from "react";
import { currency } from "@/lib/format";

// Long enough to read as motion, short enough that nobody waits for it. A
// figure someone is checking must not make them sit through a performance.
const DURATION_MS = 620;

// Ease-out cubic: fast at the start, settling gently. The value spends most of
// its time near the truth rather than near zero.
const ease = (t: number) => 1 - Math.pow(1 - t, 3);

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * A figure that counts to its value.
 *
 * Money arriving on screen is the one moment a ledger can feel alive without
 * being frivolous, so the headline numbers roll rather than blink into place.
 *
 * Two rules keep it from becoming annoying:
 *
 * - It animates from the *previous* value, not from zero, so a refresh that
 *   barely changes anything barely moves. Only the first paint sweeps up.
 * - `prefers-reduced-motion` skips it entirely — no timers, no frames, the
 *   final value rendered immediately.
 */
export function AnimatedCurrency({
  value,
  className,
  compact = false,
}: {
  value: number;
  className?: string;
  compact?: boolean;
}) {
  // Read the preference once. Rendering the final value directly in that case
  // means the effect below never runs and never sets state, which is also what
  // keeps this out of the "setState inside an effect" trap.
  const [reduced] = useState(prefersReducedMotion);
  // Seed at zero. The pages using this hold a spinner until their data
  // arrives, so the component mounts with its final figure already in hand —
  // seeding from `value` meant there was never a transition to animate.
  const [shown, setShown] = useState(0);
  // What is actually on screen right now. Deliberately *not* "the last value
  // we were asked for": React invokes effects twice in development, and a ref
  // that recorded the target up front made the second invocation believe the
  // work was already done, so nothing animated and the figure stuck at zero.
  // Advancing this only as frames are painted makes the effect idempotent.
  const displayed = useRef(0);
  const frame = useRef<number | null>(null);

  useEffect(() => {
    if (reduced) return;
    const from = displayed.current;
    const to = value;
    if (from === to) return;

    const land = () => {
      displayed.current = to;
      setShown(to);
    };

    let start: number | null = null;
    const step = (timestamp: number) => {
      if (start === null) start = timestamp;
      const progress = Math.min((timestamp - start) / DURATION_MS, 1);
      if (progress >= 1) {
        land();
        return;
      }
      const next = from + (to - from) * ease(progress);
      displayed.current = next;
      setShown(next);
      frame.current = requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);

    // requestAnimationFrame does not fire while a tab is hidden, so a
    // dashboard opened in a background tab would sit at $0.00 until somebody
    // looked at it. A decorative animation must never be able to leave a wrong
    // number on screen, and timers still run when frames do not.
    const settle = setTimeout(land, DURATION_MS + 120);

    return () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      clearTimeout(settle);
    };
  }, [reduced, value]);

  const display = reduced ? value : shown;

  return (
    // The live value is decorative while it moves; assistive technology should
    // read the real figure, not a blur of intermediate numbers.
    //
    // `data-rolling` exists so the behaviour is observable: a 620ms animation
    // is very hard to catch from a test harness after the fact, and "did it
    // actually animate?" should not be a question answered by reading code.
    <span
      aria-label={currency(value, compact)}
      className={className}
      data-rolling={display !== value ? "true" : undefined}
    >
      <span aria-hidden="true">{currency(display, compact)}</span>
    </span>
  );
}

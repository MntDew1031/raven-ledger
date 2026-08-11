"use client";

import { Check, ChevronDown } from "lucide-react";
import {
  type CSSProperties,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

export type SelectOption = {
  value: string;
  label: string;
  group?: string;
  /** Rendered as a swatch — used for category colours. */
  color?: string;
  hint?: string;
};

/**
 * Styled replacement for a native select.
 *
 * Native dropdowns are drawn by the OS, so they ignore the app's theme and
 * look wrong in dark mode. This keeps full keyboard support: type to jump,
 * arrows to move, Enter to choose, Escape to close, and it stays a real
 * labelled control for screen readers.
 */
export function SelectField({
  ariaLabel,
  className = "",
  disabled = false,
  onChange,
  options,
  placeholder = "Select…",
  value,
}: {
  ariaLabel: string;
  className?: string;
  disabled?: boolean;
  onChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  value: string;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [typed, setTyped] = useState("");
  const [menuStyle, setMenuStyle] = useState<CSSProperties>({});
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const listId = useId();

  const selected = useMemo(
    () => options.find((option) => option.value === value),
    [options, value],
  );

  const grouped = useMemo(() => {
    const buckets = new Map<string, SelectOption[]>();
    for (const option of options) {
      const key = option.group ?? "";
      buckets.set(key, [...(buckets.get(key) ?? []), option]);
    }
    return [...buckets.entries()];
  }, [options]);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      const target = event.target as Node;
      if (
        !rootRef.current?.contains(target) &&
        !listRef.current?.contains(target)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  useEffect(() => {
    if (!open) return;

    function placeMenu() {
      const trigger = triggerRef.current;
      if (!trigger) return;
      const rect = trigger.getBoundingClientRect();
      const gutter = 12;
      const gap = 5;
      const availableBelow = window.innerHeight - rect.bottom - gutter;
      const availableAbove = rect.top - gutter;
      const placeAbove = availableBelow < 220 && availableAbove > availableBelow;
      const available = placeAbove ? availableAbove : availableBelow;
      const width = Math.min(
        Math.max(rect.width, 240),
        window.innerWidth - gutter * 2,
      );
      const left = Math.min(
        Math.max(gutter, rect.left),
        window.innerWidth - width - gutter,
      );

      setMenuStyle({
        position: "fixed",
        zIndex: 240,
        left,
        right: "auto",
        width,
        maxHeight: Math.max(132, Math.min(280, available - gap)),
        top: placeAbove ? "auto" : rect.bottom + gap,
        bottom: placeAbove ? window.innerHeight - rect.top + gap : "auto",
      });
    }

    placeMenu();
    window.addEventListener("resize", placeMenu);
    // Capture scrolls from the page and any nested dialog/card scroller.
    window.addEventListener("scroll", placeMenu, true);
    return () => {
      window.removeEventListener("resize", placeMenu);
      window.removeEventListener("scroll", placeMenu, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open || !typed) return;
    const timer = window.setTimeout(() => setTyped(""), 700);
    return () => window.clearTimeout(timer);
  }, [open, typed]);

  useEffect(() => {
    if (!open) return;
    listRef.current
      ?.querySelector<HTMLElement>('[data-active="true"]')
      ?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  function commit(index: number) {
    const option = options[index];
    if (!option) return;
    onChange(option.value);
    setOpen(false);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (disabled) return;
    if (!open) {
      if (["Enter", " ", "ArrowDown", "ArrowUp"].includes(event.key)) {
        event.preventDefault();
        setActive(Math.max(0, options.findIndex((o) => o.value === value)));
        setOpen(true);
      }
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((current) => Math.min(current + 1, options.length - 1));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((current) => Math.max(current - 1, 0));
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      setActive(0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      setActive(options.length - 1);
      return;
    }
    if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault();
      commit(active);
      return;
    }
    if (event.key.length === 1 && /\S/.test(event.key)) {
      const next = (typed + event.key).toLowerCase();
      setTyped(next);
      const match = options.findIndex((option) =>
        option.label.toLowerCase().startsWith(next),
      );
      if (match >= 0) setActive(match);
    }
  }

  let flatIndex = -1;

  return (
    <div className={`select-field ${className}`} ref={rootRef}>
      <button
        aria-controls={open ? listId : undefined}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={ariaLabel}
        className="select-trigger"
        disabled={disabled}
        onClick={() => {
          if (disabled) return;
          setActive(Math.max(0, options.findIndex((o) => o.value === value)));
          setOpen((current) => !current);
        }}
        onKeyDown={onKeyDown}
        ref={triggerRef}
        type="button"
      >
        <span className="select-value">
          {selected?.color && (
            <em
              aria-hidden="true"
              className="select-swatch"
              style={{ backgroundColor: selected.color }}
            />
          )}
          <span className={selected ? "" : "select-placeholder"}>
            {selected?.label ?? placeholder}
          </span>
        </span>
        <ChevronDown aria-hidden="true" size={13} />
      </button>

      {open &&
        createPortal(
          <div
            aria-label={ariaLabel}
            className="select-menu select-menu-portal"
            id={listId}
            onKeyDown={onKeyDown}
            ref={listRef}
            role="listbox"
            style={menuStyle}
            tabIndex={-1}
          >
            {grouped.map(([group, groupOptions]) => (
              <div key={group || "_"}>
                {group && <p className="select-group">{group}</p>}
                {groupOptions.map((option) => {
                  flatIndex += 1;
                  const index = flatIndex;
                  const isSelected = option.value === value;
                  return (
                    <button
                      aria-selected={isSelected}
                      className="select-option"
                      data-active={index === active}
                      key={option.value}
                      onClick={() => commit(index)}
                      onMouseEnter={() => setActive(index)}
                      role="option"
                      type="button"
                    >
                      {option.color && (
                        <em
                          aria-hidden="true"
                          className="select-swatch"
                          style={{ backgroundColor: option.color }}
                        />
                      )}
                      <span>
                        {option.label}
                        {option.hint && <small>{option.hint}</small>}
                      </span>
                      {isSelected && <Check size={12} />}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>,
          document.body,
        )}
    </div>
  );
}

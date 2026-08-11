"use client";

import {
  AlertCircle,
  BarChart3,
  Bell,
  CheckCircle2,
  Command,
  Feather,
  Eye,
  EyeOff,
  LayoutDashboard,
  LogOut,
  Menu,
  PieChart,
  Plus,
  ReceiptText,
  Repeat,
  LoaderCircle,
  Search,
  Tags,
  Settings,
  Sparkles,
  WalletCards,
  Wand2,
  X,
} from "lucide-react";
import Image from "next/image";
import { LedgerSwitcher } from "@/components/ledger-switcher";
import { SandboxBanner } from "@/components/sandbox-banner";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { applyAppearance, UserProfile } from "@/lib/profile";

type Session = {
  user: UserProfile;
  household_name: string;
  role: "owner" | "member" | "viewer";
};

const navigation = [
  { label: "Dashboard", href: "/", icon: LayoutDashboard, section: "Overview" },
  { label: "Accounts", href: "/accounts", icon: WalletCards, section: "Money" },
  { label: "Transactions", href: "/transactions", icon: ReceiptText, section: "Money" },
  { label: "Budget", href: "/budgets", icon: PieChart, section: "Plan" },
  { label: "Categories", href: "/categories", icon: Tags, section: "Plan" },
  // Rules, recurring bills and the organizer are one idea — things Raven does
  // so you do not have to — and they were three entries out of eleven. Folded
  // together they shorten the list, and the Organizer becomes something you
  // find rather than something you have to already know about.
  { label: "Automation", href: "/automation", icon: Wand2, section: "Plan" },
  { label: "Reports", href: "/reports", icon: BarChart3, section: "Explore" },
  { label: "Assistant", href: "/assistant", icon: Sparkles, section: "Explore" },
  { label: "Settings", href: "/settings", icon: Settings, section: "Account" },
];

const mobileNavigation = navigation.slice(0, 4);

export function AppShell({
  active,
  children,
}: {
  active: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  // Plain-English search. Separate from the palette's own matching so that
  // typing still filters pages instantly and only Enter spends a model call.
  const [interpreting, setInterpreting] = useState(false);
  const [interpretError, setInterpretError] = useState("");
  const [paletteQuery, setPaletteQuery] = useState("");
  const [quickOpen, setQuickOpen] = useState(false);
  const [noticeOpen, setNoticeOpen] = useState(false);
  const [needsReview, setNeedsReview] = useState(0);
  const [balancesHidden, setBalancesHidden] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiFetch<Session>("/auth/me")
      .then((result) => {
        if (!cancelled) {
          setSession(result);
          applyAppearance(result.user);
        }
      })
      .catch(() => {
        // The request proxy handles expired sessions on the next navigation.
      });
    apiFetch<{ needs_review: number }>("/dashboard/summary")
      .then((result) => {
        if (!cancelled) setNeedsReview(result.needs_review);
      })
      .catch(() => undefined);
    const updateProfile = (event: Event) => {
      const profile = (event as CustomEvent<UserProfile>).detail;
      setSession((current) =>
        current ? { ...current, user: profile } : current,
      );
    };
    window.addEventListener("raven-profile-updated", updateProfile);
    return () => {
      cancelled = true;
      window.removeEventListener("raven-profile-updated", updateProfile);
    };
  }, []);

  useEffect(() => {
    const hidden = window.localStorage.getItem("raven-hide-balances") === "true";
    const frame = window.requestAnimationFrame(() => {
      setBalancesHidden(hidden);
      document.documentElement.dataset.private = String(hidden);
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  function toggleBalancePrivacy() {
    setBalancesHidden((current) => {
      const next = !current;
      document.documentElement.dataset.private = String(next);
      window.localStorage.setItem("raven-hide-balances", String(next));
      return next;
    });
  }

  useEffect(() => {
    const openPalette = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((current) => !current);
        setQuickOpen(false);
        setNoticeOpen(false);
      }
    };
    window.addEventListener("keydown", openPalette);
    return () => window.removeEventListener("keydown", openPalette);
  }, []);

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.body.classList.add("navigation-open");
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.classList.remove("navigation-open");
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const displayName = session?.user.display_name ?? "Household member";
  const initial = displayName.slice(0, 1).toUpperCase();
  const paletteItems = [
    ...navigation.map((item) => ({
      label: item.label,
      detail: `Go to ${item.section.toLowerCase()}`,
      href: item.href,
      icon: item.icon,
    })),
    { label: "Add an account", detail: "Manual or Plaid", href: "/accounts?action=add", icon: WalletCards },
    { label: "Add a transaction", detail: "Record activity", href: "/transactions?action=add", icon: ReceiptText },
    { label: "Review uncategorized", detail: `${needsReview} waiting`, href: "/transactions?review=needs-review", icon: Sparkles },
  ].filter((item) => {
    const haystack = `${item.label} ${item.detail}`.toLowerCase();
    return paletteQuery
      .toLowerCase()
      .trim()
      .split(/\s+/)
      .filter(Boolean)
      .every((token) => haystack.includes(token));
  });

  async function signOut() {
    setSigningOut(true);
    try {
      await fetch("/api/v1/auth/logout", {
        credentials: "include",
        method: "POST",
      });
    } finally {
      window.location.replace("/login");
    }
  }

  return (
    <div className="app-shell">
      <aside
        aria-label="Application navigation"
        className={`sidebar ${open ? "open" : ""}`}
      >
        <div className="brand">
          <span className="brand-mark">
            <Feather size={18} />
          </span>
          <span>
            <strong>Raven</strong>
            <small>Ledger</small>
          </span>
          <button
            aria-label="Close navigation"
            className="sidebar-close"
            onClick={() => setOpen(false)}
          >
            <X size={18} />
          </button>
        </div>
        <nav aria-label="Main navigation">
          {navigation.map((item, index) => {
            const Icon = item.icon;
            return (
              <div className="nav-item-wrap" key={item.label}>
                {(index === 0 || navigation[index - 1].section !== item.section) && (
                  <span className="nav-section-label">{item.section}</span>
                )}
                <a
                  aria-current={active === item.label ? "page" : undefined}
                  className={active === item.label ? "active" : ""}
                  href={item.href}
                  onClick={() => setOpen(false)}
                >
                  <Icon size={18} />
                  {item.label}
                </a>
              </div>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <div className="sync-dot" />
          <div>
            <strong>Private household data</strong>
            <small>Protected session</small>
          </div>
        </div>
      </aside>

      {open && (
        <button
          aria-label="Close navigation overlay"
          className="sidebar-overlay"
          onClick={() => setOpen(false)}
        />
      )}

      <main className={`workspace workspace-${active.toLowerCase()}`}>
        <header className="topbar">
          <button
            aria-label="Open navigation"
            className="menu-button"
            onClick={() => setOpen(true)}
          >
            <Menu size={20} />
          </button>
          <LedgerSwitcher currentName={session?.household_name ?? ""} />
          <div className="household-switcher">
            <span className="avatar-stack">
              {session?.user.avatar_url ? (
                <Image
                  alt=""
                  className="avatar-image"
                  height={29}
                  src={session.user.avatar_url}
                  unoptimized
                  width={29}
                />
              ) : (
                <i>{initial}</i>
              )}
            </span>
            <span>
              <strong>{session?.household_name ?? "Your household"}</strong>
              <small>
                {displayName}
                {/* Dropped on a phone rather than truncated. There is no room
                    for "Alex · owner" beside six controls at 375px, and
                    clipping it to "Alex · o…" spends the space on nothing —
                    the role is on the settings page, the name is what
                    identifies who is signed in. */}
                <span className="hide-on-mobile">
                  {" · "}
                  {session?.role ?? "member"}
                </span>
              </small>
            </span>
          </div>
          <div className="topbar-actions">
            <button
              aria-label="Search and quick navigation"
              className="command-trigger"
              onClick={() => setPaletteOpen(true)}
              type="button"
            >
              <Search size={15} /> <span>Jump anywhere</span><kbd>⌘ K</kbd>
            </button>
            <button
              aria-pressed={balancesHidden}
              aria-label={balancesHidden ? "Show financial amounts" : "Hide financial amounts"}
              className={`icon-button privacy-button ${balancesHidden ? "active" : ""}`}
              onClick={toggleBalancePrivacy}
              title={balancesHidden ? "Show amounts" : "Hide amounts for screen sharing"}
              type="button"
            >
              {balancesHidden ? <EyeOff size={17} /> : <Eye size={17} />}
            </button>
            <div className="topbar-popover-wrap">
              <button
                aria-expanded={quickOpen}
                aria-label="Quick add"
                className="icon-button quick-add-button"
                onClick={() => {
                  setQuickOpen((current) => !current);
                  setNoticeOpen(false);
                }}
                type="button"
              >
                <Plus size={18} />
              </button>
              {quickOpen && (
                <div className="topbar-popover quick-popover">
                  <p className="eyebrow">Quick create</p>
                  <a href="/transactions?action=add"><ReceiptText size={16} /><span><strong>Transaction</strong><small>Record income or spending</small></span></a>
                  <a href="/accounts?action=add"><WalletCards size={16} /><span><strong>Account</strong><small>Manual or connected</small></span></a>
                  <a href="/budgets"><PieChart size={16} /><span><strong>Monthly plan</strong><small>Shape this month</small></span></a>
                </div>
              )}
            </div>
            <div className="topbar-popover-wrap">
            <button
              aria-expanded={noticeOpen}
              aria-label="Notifications"
              className="icon-button"
              onClick={() => {
                setNoticeOpen((current) => !current);
                setQuickOpen(false);
              }}
              type="button"
            >
              <Bell size={18} />
              {needsReview > 0 && <span className="notification-dot" />}
            </button>
              {noticeOpen && (
                <div className="topbar-popover notice-popover">
                  <p className="eyebrow">Household pulse</p>
                  {needsReview ? (
                    <a href="/transactions?review=needs-review">
                      <AlertCircle className="negative" size={18} />
                      <span><strong>{needsReview} transaction{needsReview === 1 ? "" : "s"} need review</strong><small>Confirm categories to keep reports accurate.</small></span>
                    </a>
                  ) : (
                    <div className="notice-clear"><CheckCircle2 size={19} /><span><strong>You’re all caught up</strong><small>No transactions need review.</small></span></div>
                  )}
                  <a href="/automation"><Repeat size={17} /><span><strong>Upcoming bills</strong><small>See the next 30 days</small></span></a>
                </div>
              )}
            </div>
            <button
              aria-label="Sign out"
              className="icon-button signout-button"
              disabled={signingOut}
              onClick={signOut}
              title="Sign out"
            >
              <LogOut size={17} />
            </button>
            <a
              aria-label="Open profile settings"
              className="profile-avatar"
              href="/settings#profile"
              title="Profile settings"
            >
              {session?.user.avatar_url ? (
                <Image
                  alt=""
                  height={36}
                  src={session.user.avatar_url}
                  unoptimized
                  width={36}
                />
              ) : (
                initial
              )}
            </a>
          </div>
        </header>
        <div className="content">
          <SandboxBanner householdName={session?.household_name ?? ""} />
          {children}
        </div>
        <nav aria-label="Mobile navigation" className="mobile-tabbar">
          {mobileNavigation.map((item) => {
            const Icon = item.icon;
            const selected = active === item.label;
            return (
              <a
                aria-current={selected ? "page" : undefined}
                className={selected ? "active" : ""}
                href={item.href}
                key={item.label}
              >
                <Icon size={19} />
                <span>{item.label}</span>
              </a>
            );
          })}
          <button
            aria-expanded={open}
            aria-label="Open all navigation"
            className={
              mobileNavigation.some((item) => item.label === active)
                ? ""
                : "active"
            }
            onClick={() => setOpen(true)}
          >
            <Menu size={19} />
            <span>More</span>
          </button>
        </nav>
        {paletteOpen && (
          <div
            className="command-layer"
            onMouseDown={() => setPaletteOpen(false)}
            role="presentation"
          >
            <section
              aria-label="Search Raven Ledger"
              aria-modal="true"
              className="command-palette"
              onMouseDown={(event) => event.stopPropagation()}
              role="dialog"
            >
              <div className="command-search">
                <Search size={18} />
                <input
                  autoFocus
                  onChange={(event) => setPaletteQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") setPaletteOpen(false);
                    if (event.key !== "Enter") return;
                    // A phrase that matches a page opens it. Anything else is
                    // treated as a description of transactions and handed to
                    // the model — which is the only path that costs anything,
                    // so it is never taken while merely typing.
                    if (paletteItems[0]) {
                      window.location.assign(paletteItems[0].href);
                      return;
                    }
                    const question = paletteQuery.trim();
                    if (!question || interpreting) return;
                    setInterpreting(true);
                    setInterpretError("");
                    void apiFetch<{
                      filters: Record<string, string | number>;
                      understood: boolean;
                    }>("/transactions/search/interpret", {
                      method: "POST",
                      body: JSON.stringify({ query: question }),
                    })
                      .then((result) => {
                        if (!result.understood) {
                          setInterpretError(
                            "Raven could not turn that into a search. Try naming a merchant, an amount, or a period.",
                          );
                          return;
                        }
                        const params = new URLSearchParams();
                        Object.entries(result.filters).forEach(([key, value]) =>
                          params.set(key, String(value)),
                        );
                        window.location.assign(`/transactions?${params}`);
                      })
                      .catch((reason: unknown) =>
                        setInterpretError(
                          reason instanceof Error
                            ? reason.message
                            : "That search did not work",
                        ),
                      )
                      .finally(() => setInterpreting(false));
                  }}
                  placeholder="Search pages, or describe transactions…"
                  value={paletteQuery}
                />
                <kbd>esc</kbd>
              </div>
              <div className="command-results">
                {paletteItems.length ? paletteItems.map((item) => {
                  const Icon = item.icon;
                  return (
                    <a href={item.href} key={`${item.href}-${item.label}`}>
                      <span><Icon size={17} /></span>
                      <div><strong>{item.label}</strong><small>{item.detail}</small></div>
                      <Command size={13} />
                    </a>
                  );
                }) : (
                  <div className="command-empty">
                    {interpreting ? (
                      <>
                        <LoaderCircle className="spin" size={14} /> Working out
                        what you mean…
                      </>
                    ) : interpretError ? (
                      <span className="negative">{interpretError}</span>
                    ) : paletteQuery.trim() ? (
                      <>
                        No page matches. Press <kbd>Enter</kbd> to search your
                        transactions for “{paletteQuery.trim()}”.
                      </>
                    ) : (
                      "Search pages, or describe what you are looking for."
                    )}
                  </div>
                )}
              </div>
              <footer><span>Raven command menu</span><small>Press Enter to open the first result</small></footer>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}

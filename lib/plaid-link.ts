import { apiFetch } from "@/lib/api";

/**
 * OAuth institutions send the browser to the bank and back, which destroys all
 * in-memory React state. The link token and what the flow was for have to
 * survive that round trip, so they are parked in localStorage — Plaid's own
 * OAuth examples do the same — and cleared the moment the flow ends.
 */
const STORAGE_KEY = "raven-plaid-link";

export type PendingLink = {
  /** The original link token. Plaid requires the same one after the redirect. */
  token: string;
  /** Set when repairing an existing connection instead of adding a new one. */
  connectionId?: string;
  /** Where to send the person once the connection is finished. */
  returnTo: string;
};

export function savePendingLink(pending: PendingLink) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(pending));
  } catch {
    // Private browsing modes can refuse storage. Desktop Link still works;
    // only the OAuth return leg depends on this.
  }
}

export function loadPendingLink(): PendingLink | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PendingLink>;
    if (typeof parsed.token !== "string" || !parsed.token) return null;
    return {
      token: parsed.token,
      connectionId:
        typeof parsed.connectionId === "string" ? parsed.connectionId : undefined,
      // Never follow an absolute URL out of the app.
      returnTo:
        typeof parsed.returnTo === "string" &&
        parsed.returnTo.startsWith("/") &&
        !parsed.returnTo.startsWith("//")
          ? parsed.returnTo
          : "/settings",
    };
  } catch {
    return null;
  }
}

export function clearPendingLink() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to clean up if storage is unavailable.
  }
}

/** True when Plaid has just handed the browser back after an OAuth bank. */
export function isOAuthReturn() {
  return (
    typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).has("oauth_state_id")
  );
}

/**
 * Finish a Link session. A new institution exchanges its public token; a
 * repaired one only needs the sync re-queued, because its access token is
 * already stored. Plaid omits the public token in update mode, which is why it
 * arrives nullable.
 */
export async function completePlaidLink({
  publicToken,
  institutionName,
  connectionId,
}: {
  publicToken: string | null;
  institutionName?: string;
  connectionId?: string;
}) {
  if (connectionId) {
    await apiFetch(`/plaid/connections/${connectionId}/updated`, {
      method: "POST",
    });
    return;
  }
  if (!publicToken) {
    throw new Error("Plaid did not return a public token for this connection.");
  }
  await apiFetch("/plaid/exchange", {
    method: "POST",
    body: JSON.stringify({
      public_token: publicToken,
      institution_name: institutionName,
    }),
  });
}

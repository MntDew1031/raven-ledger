"use client";

import { AlertCircle, LoaderCircle } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  PlaidLinkOnSuccess,
  PlaidLinkOptions,
  usePlaidLink,
} from "react-plaid-link";
import {
  clearPendingLink,
  completePlaidLink,
  loadPendingLink,
  PendingLink,
} from "@/lib/plaid-link";

type Phase = "resuming" | "finishing" | "done" | "failed";

function pendingSessionExists() {
  return loadPendingLink() !== null;
}

/**
 * Landing page for Plaid's OAuth redirect. An OAuth bank takes the browser off
 * site, so Link has to be rebuilt here with the original token plus the
 * redirect URL Plaid appended `oauth_state_id` to.
 */
export function PlaidOAuthReturn() {
  // Read once during the first render. This component is loaded client-only,
  // so localStorage is available and no effect round trip is needed.
  const [pending] = useState<PendingLink | null>(() => loadPendingLink());
  const [phase, setPhase] = useState<Phase>(() =>
    pendingSessionExists() ? "resuming" : "failed",
  );
  const [message, setMessage] = useState(() =>
    pendingSessionExists()
      ? ""
      : "This connection could not be resumed. It may have been started in a different browser, or too long ago.",
  );

  const finish = useCallback(
    async (publicToken: string | null, institutionName?: string) => {
      setPhase("finishing");
      try {
        await completePlaidLink({
          publicToken,
          institutionName,
          connectionId: pending?.connectionId,
        });
        clearPendingLink();
        setPhase("done");
        window.location.replace(pending?.returnTo ?? "/settings");
      } catch (reason) {
        clearPendingLink();
        setPhase("failed");
        setMessage(
          reason instanceof Error
            ? reason.message
            : "Plaid could not finish connecting.",
        );
      }
    },
    [pending],
  );

  const onSuccess = useCallback<PlaidLinkOnSuccess>(
    (publicToken, metadata) => {
      void finish(publicToken, metadata.institution?.name ?? undefined);
    },
    [finish],
  );

  const config: PlaidLinkOptions = useMemo(
    () => ({
      token: pending?.token ?? null,
      receivedRedirectUri:
        typeof window === "undefined" ? undefined : window.location.href,
      onSuccess,
      onExit: (error) => {
        // Link also exits immediately when it was never given a token, which
        // is exactly the stale-session case. Keep the more accurate message.
        if (!pending) return;
        clearPendingLink();
        setPhase("failed");
        setMessage(
          error
            ? "Your bank did not finish authorizing the connection."
            : "The connection was canceled.",
        );
      },
    }),
    [pending, onSuccess],
  );

  const { open, ready } = usePlaidLink(config);

  useEffect(() => {
    if (ready && pending && phase === "resuming") open();
  }, [ready, pending, phase, open]);

  const returnTo = pending?.returnTo ?? "/settings";

  return (
    <div className="onboarding-loading">
      {phase === "failed" ? (
        <>
          <AlertCircle className="negative" size={22} aria-hidden="true" />
          <p className="negative">{message}</p>
          <Link className="ghost-button" href={returnTo}>
            Back to Raven Ledger
          </Link>
        </>
      ) : (
        <>
          <LoaderCircle className="spin" size={22} aria-hidden="true" />
          <p>
            {phase === "finishing"
              ? "Saving your connection…"
              : "Returning from your bank…"}
          </p>
        </>
      )}
    </div>
  );
}

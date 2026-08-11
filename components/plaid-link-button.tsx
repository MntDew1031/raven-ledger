"use client";

import { Link2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  PlaidLinkOnSuccess,
  PlaidLinkOptions,
  usePlaidLink,
} from "react-plaid-link";
import { apiFetch } from "@/lib/api";
import {
  clearPendingLink,
  completePlaidLink,
  savePendingLink,
} from "@/lib/plaid-link";

export function PlaidLinkButton({
  onConnected,
  label = "Connect with Plaid",
  connectionId,
}: {
  onConnected?: () => void;
  label?: string;
  connectionId?: string;
}) {
  const [token, setToken] = useState<string | null>(null);
  const [status, setStatus] = useState("");

  useEffect(() => {
    const path = connectionId
      ? `/plaid/connections/${connectionId}/link-token`
      : "/plaid/link-token";
    apiFetch<{ link_token: string }>(path, { method: "POST" })
      .then((response) => setToken(response.link_token))
      .catch((reason: unknown) =>
        setStatus(
          reason instanceof Error
            ? reason.message
            : "Plaid could not be initialized.",
        ),
      );
  }, [connectionId]);

  const onSuccess = useCallback<PlaidLinkOnSuccess>(
    async (publicToken, metadata) => {
      setStatus("Securely connecting…");
      try {
        await completePlaidLink({
          publicToken,
          institutionName: metadata.institution?.name ?? undefined,
          connectionId,
        });
        setStatus(
          connectionId
            ? "Connection repaired. A fresh sync is queued."
            : "Connected. The first sync is queued.",
        );
        onConnected?.();
      } catch (reason) {
        setStatus(
          reason instanceof Error
            ? reason.message
            : "Plaid could not finish connecting.",
        );
      } finally {
        clearPendingLink();
      }
    },
    [connectionId, onConnected],
  );

  const config: PlaidLinkOptions = {
    token,
    onSuccess,
    onExit: (error) => {
      clearPendingLink();
      if (error) setStatus("Connection was not completed.");
    },
  };
  const { open, ready } = usePlaidLink(config);

  function start() {
    if (!token) return;
    // An OAuth bank navigates the browser away from this page, so the flow has
    // to be recoverable from wherever Plaid sends the person back.
    savePendingLink({
      token,
      connectionId,
      returnTo: `${window.location.pathname}${window.location.search}`,
    });
    open();
  }

  return (
    <div>
      <button
        className="primary-button"
        disabled={!ready}
        onClick={start}
        type="button"
      >
        <Link2 size={15} /> {label}
      </button>
      {status && <p className="subtle">{status}</p>}
    </div>
  );
}

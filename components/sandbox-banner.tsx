"use client";

import { FlaskConical, LogOut } from "lucide-react";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Ledger = { id: string; name: string; is_sandbox: boolean };

/**
 * Say, constantly and unmissably, that this is not the real ledger.
 *
 * A sandbox is an exact copy — that is the entire point — so nothing about the
 * numbers on screen can tell you where you are. A small badge in the header is
 * not enough: on a phone it collapses to an icon, and the one moment it
 * matters is the moment somebody has forgotten to look.
 */
export function SandboxBanner({ householdName }: { householdName: string }) {
  const [ledgers, setLedgers] = useState<Ledger[]>([]);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiFetch<Ledger[]>("/households/ledgers")
      .then((rows) => {
        if (!cancelled) setLedgers(rows);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [householdName]);

  const current = ledgers.find((item) => item.name === householdName);
  const home = ledgers.find((item) => !item.is_sandbox);
  if (!current?.is_sandbox) return null;

  async function leave() {
    if (!home) return;
    setLeaving(true);
    try {
      await apiFetch("/households/switch", {
        method: "POST",
        body: JSON.stringify({ household_id: home.id }),
      });
      window.location.reload();
    } catch {
      setLeaving(false);
    }
  }

  return (
    <div className="sandbox-banner" role="status">
      <FlaskConical size={15} />
      <span>
        <strong>Sandbox — {current.name}</strong>
        <small>
          A copy of your ledger. Nothing you change here touches the real one.
        </small>
      </span>
      {home && (
        <button disabled={leaving} onClick={() => void leave()} type="button">
          <LogOut size={13} /> Back to {home.name}
        </button>
      )}
    </div>
  );
}

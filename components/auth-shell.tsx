import { CreditCard } from "lucide-react";
import { ReactNode } from "react";

export function AuthShell({
  headline,
  children,
  intro,
}: {
  headline: string;
  children: ReactNode;
  intro: string;
}) {
  return (
    <main className="login-shell">
      <section className="login-art">
        <div className="brand">
          <span className="brand-mark">
            <CreditCard size={18} />
          </span>
          <span>
            <strong>Raven</strong>
            <small>Ledger</small>
          </span>
        </div>
        <div>
          <h1>{headline}</h1>
          <p>{intro}</p>
        </div>
        <small>Self-hosted household finance</small>
      </section>
      <section className="login-form-wrap">{children}</section>
    </main>
  );
}

import { useEffect, useState } from "react";
import { Check, CreditCard, ShieldCheck } from "lucide-react";
import { api } from "./api";

type Subscription = {
  enabled: boolean;
  active: boolean;
  status: string;
  tax_behavior: "inclusive" | "exclusive";
  paid_until: string | null;
  cancel_at_period_end: boolean;
  can_manage: boolean;
};

export function Billing({
  botId,
  onAccess,
}: {
  botId: string;
  onAccess: (allowed: boolean) => void;
}) {
  const [subscription, setSubscription] = useState<Subscription>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let stopped = false;
    async function load() {
      try {
        const returning =
          new URLSearchParams(location.search).get("billing") === "return";
        const result = await api<Subscription>(
          `/api/bots/${botId}/billing${returning ? "/refresh" : ""}`,
          returning ? {} : undefined,
        );
        if (!stopped) {
          setSubscription(result);
          onAccess(!result.enabled || result.active);
        }
      } catch (e) {
        if (!stopped) setError((e as Error).message);
      }
    }
    void load();
    return () => {
      stopped = true;
    };
  }, [botId, onAccess]);

  async function action(kind: "checkout" | "portal" | "refresh") {
    setBusy(true);
    setError("");
    try {
      if (kind === "refresh") {
        const result = await api<Subscription>(
          `/api/bots/${botId}/billing/refresh`,
          {},
        );
        setSubscription(result);
        onAccess(!result.enabled || result.active);
      } else {
        const result = await api<{ url: string }>(
          `/api/bots/${botId}/billing/${kind}`,
          {},
        );
        window.location.assign(result.url);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (subscription && !subscription.enabled) return null;
  return (
    <div className="billing" aria-label="Abonnemang">
      <div className="billing-heading">
        <span className="billing-icon"><CreditCard size={21} /></span>
        <div>
          <p className="eyebrow">Publicera assistenten</p>
          <h3>En chatbot · 399 kr/månad</h3>
        </div>
      </div>
      {subscription && (
        <p className="small">
          {subscription.tax_behavior === "inclusive"
            ? "Inklusive moms."
            : "Exklusive moms."}{" "}
          Förnyas månadsvis. Säg upp i kundportalen inför nästa period.
        </p>
      )}
      {!subscription && !error && <p role="status">Hämtar abonnemang…</p>}
      {subscription && (
        <>
          <p className={subscription.active ? "billing-status active" : "billing-status"} role="status">
            {subscription.active && <Check size={17} />}
            {subscription.active
              ? subscription.cancel_at_period_end
                ? `Uppsagt. Aktivt till ${new Date(subscription.paid_until!).toLocaleDateString("sv-SE")}.`
                : "Ditt abonnemang är aktivt."
              : subscription.status === "past_due"
                ? "Betalningen behöver uppdateras i kundportalen."
                : "Prova gratis här. Aktivera abonnemanget för att öppna chatten på din hemsida."}
          </p>
          <div className="actions">
            {!subscription.active &&
              ["none", "canceled", "incomplete_expired"].includes(
                subscription.status,
              ) && (
                <button disabled={busy} onClick={() => action("checkout")}>
                  Fortsätt till betalning · 399 kr/mån
                </button>
              )}
            {subscription.can_manage && (
              <button
                className="secondary"
                disabled={busy}
                onClick={() => action("portal")}
              >
                Hantera abonnemang
              </button>
            )}
            {!subscription.active && (
              <button
                className="text-button"
                disabled={busy}
                onClick={() => action("refresh")}
              >
                Kontrollera betalningen
              </button>
            )}
          </div>
          {!subscription.active && (
            <div className="billing-trust">
              <ShieldCheck size={18} />
              <span>Säker betalning hos Stripe. Kortuppgifter passerar aldrig Coastworks.</span>
            </div>
          )}
        </>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

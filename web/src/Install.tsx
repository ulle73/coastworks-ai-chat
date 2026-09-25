import { useEffect, useState, type FormEvent } from "react";
import { ArrowRight, Check, Copy } from "lucide-react";
import { api, type Bot } from "./api";
import { Billing } from "./Billing";

export function Install({
  bot,
  confirmed = false,
}: {
  bot: Bot;
  confirmed?: boolean;
}) {
  const [stage, setStage] = useState(confirmed ? "code" : "email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [published, setPublished] = useState(bot.published);
  const [paid, setPaid] = useState(false);
  useEffect(() => {
    api<{ code: string; published: boolean }>(
      `/api/bots/${bot.id}/installation`,
    )
      .then((r) => {
        setCode(r.code);
        setPublished(r.published);
        setStage("code");
      })
      .catch((e) => {
        if (confirmed) setError(e.message);
      });
  }, [bot.id, confirmed]);
  async function claim(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(`/api/bots/${bot.id}/claim`, { email });
      setStage("sent");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function publish() {
    setBusy(true);
    setError("");
    try {
      await api(`/api/bots/${bot.id}/publish`, {});
      setPublished(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="install">
      {stage === "email" && (
        <>
          <h2>Ge assistenten ett hem.</h2>
          <p>
            Ange din e-post så sparar vi din assistent och skickar länken till
            din installationskod. Inget lösenord.
          </p>
          <form onSubmit={claim} className="stack">
            <label htmlFor="email">Din e-post</label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="du@dittforetag.se"
              required
            />
            <button disabled={busy}>
              Skicka min länk <ArrowRight size={18} />
            </button>
          </form>
          <p className="small">
            Vi använder din e-post för åtkomst till assistenten.
          </p>
        </>
      )}
      {stage === "sent" && (
        <>
          <Check className="success-icon" />
          <h2>Kolla din inkorg.</h2>
          <p>
            Vi har skickat en länk till {email}. Bekräfta din e-post för att
            hämta installationskoden.
          </p>
          <button className="text-button" onClick={() => setStage("email")}>
            Ändra e-post eller skicka igen
          </button>
        </>
      )}
      {stage === "code" && (
        <>
          <Billing botId={bot.id} onAccess={setPaid} />
          <h2>
            {published
              ? "Din assistent är på plats."
              : "En rad kod. Sedan är ni igång."}
          </h2>
          <p>
            Klistra in koden före &lt;/body&gt; på din hemsida. I WordPress kan
            du lägga den i ett fält för sidfotsskript.
          </p>
          <pre>
            <code>{code || "Hämtar din kod…"}</code>
          </pre>
          <div className="actions">
            <button
              disabled={!code}
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(code);
                  setCopied(true);
                } catch {
                  setError("Markera koden ovan och kopiera den manuellt.");
                }
              }}
            >
              {copied ? <Check size={18} /> : <Copy size={18} />}{" "}
              {copied ? "Kopierat" : "Kopiera kod"}
            </button>
            <button
              className="secondary"
              disabled={busy || published || !paid}
              onClick={publish}
            >
              {published
                ? "Installationen är bekräftad"
                : "Jag har lagt in koden"}
            </button>
          </div>
          <p className="small">
            Vi kontrollerar installationen innan chatten öppnas för dina
            besökare.
          </p>
        </>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

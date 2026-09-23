import { useState, type FormEvent } from "react";
import { ArrowRight, Check } from "lucide-react";
import { api } from "./api";
export function Managed() {
  const [open, setOpen] = useState(false);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const data = Object.fromEntries(new FormData(e.currentTarget));
    try {
      await api("/api/managed", data);
      setSent(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section id="managed" className="managed">
      <div className="managed-intro">
        <h2>Vill du att vi tar hand om allt?</h2>
        <div>
          <p>
            Vi hjälper dig med hela uppsättningen, kvalitetssäkrar innehållet
            och sköter den löpande uppdateringen.
          </p>
          <button onClick={() => setOpen(!open)} aria-expanded={open}>
            Berätta om ditt företag <ArrowRight size={18} />
          </button>
        </div>
      </div>
      {open && (
        <div className="managed-details">
          <div>
            <h3>En tjänst, med människor bakom.</h3>
            <p>
              Vi kartlägger kundernas frågor, kompletterar med era dokument,
              produktdata och FAQ och testar svaren tillsammans med er.
            </p>
            <p>
              Ni får en ansvarig kontakt, överenskommen uppföljning och löpande
              underhåll. Intern information publiceras först efter ert
              godkännande.
            </p>
          </div>
          {sent ? (
            <div role="status">
              <Check />
              <h3>Tack, din förfrågan är sparad.</h3>
              <p>Vi återkommer via e-post och pratar om vad ni behöver.</p>
            </div>
          ) : (
            <form className="stack" onSubmit={submit}>
              <label htmlFor="managed-email">E-post</label>
              <input
                id="managed-email"
                name="email"
                type="email"
                autoComplete="email"
                required
              />
              <label htmlFor="website">Företagets hemsida</label>
              <input id="website" name="website" required maxLength={2048} />
              <label htmlFor="needs">Vad vill ni ha hjälp med?</label>
              <textarea
                id="needs"
                name="message"
                required
                minLength={10}
                maxLength={4000}
                rows={3}
              />
              <button disabled={busy}>
                Skicka förfrågan <ArrowRight size={18} />
              </button>
              {error && (
                <p role="alert" className="error">
                  {error}
                </p>
              )}
            </form>
          )}
        </div>
      )}
    </section>
  );
}

import { useState, type FormEvent } from "react";
import { api } from "./api";

export function Access() {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await api<{ message: string }>("/api/access", { email });
      setMessage(r.message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div>
      <button
        className="text-button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        Hämta min assistent
      </button>
      {open && (
        <form className="stack access" onSubmit={submit}>
          <label htmlFor="access-email">E-post för din sparade assistent</label>
          <input
            id="access-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <button disabled={busy}>Skicka åtkomstlänk</button>
          {message && <p role="status">{message}</p>}
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
        </form>
      )}
    </div>
  );
}
